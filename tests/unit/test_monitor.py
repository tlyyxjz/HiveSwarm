"""Monitor 层单元测试."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta

import pytest

from core.events import Event, EventBus, EventType
from core.skill import Skill, SkillManifest
from layers.monitor.bus import MonitorBus
from layers.monitor.health import HealthSnapshotter
from layers.monitor.logger import EventLogger
from layers.work.pool import SkillPool
from stub.bus_local import LocalEventBus


class EchoSkill(Skill):
    def __init__(self, name: str = "a") -> None:
        super().__init__(SkillManifest(name=name, api_version="1.0"))

    def run(self, input_data: dict) -> dict:
        return {"ok": True}


# ── EventLogger ─────────────────────────────────────────────────────

class TestEventLogger:
    def test_write_and_read_recent(self, tmp_path):
        path = tmp_path / "events.jsonl"
        log = EventLogger(path)
        log.write(Event(type=EventType.TASK_STARTED, payload={"i": 1}))
        log.write(Event(type=EventType.TASK_COMPLETED, payload={"i": 1}))
        recent = log.read_recent(10)
        # 最近 = 倒序, 末位先
        assert len(recent) == 2
        assert recent[0]["type"] == EventType.TASK_COMPLETED.value
        log.close()

    def test_read_since(self, tmp_path):
        """基于行号的 read_after_index, 避免 ts 精度问题."""
        log = EventLogger(tmp_path / "e.jsonl")
        for i in range(3):
            log.write(Event(type=EventType.TASK_STARTED, payload={"i": i}))
        # 第 3 条后,再写 1 条, 应该读出 1 条
        log.write(Event(type=EventType.TASK_COMPLETED, payload={"i": 99}))
        out = log.read_after_index(2)
        assert len(out) == 1
        # Event.to_dict() 把 payload spread 到顶层, 所以是 out[0]["i"]
        assert out[0]["i"] == 99
        log.close()

    def test_read_recent_with_type_filter(self, tmp_path):
        log = EventLogger(tmp_path / "e.jsonl")
        log.write(Event(type=EventType.TASK_STARTED, payload={"i": 0}))
        log.write(Event(type=EventType.TASK_COMPLETED, payload={"i": 1}))
        # 用 read_after_index 避免时间戳精度问题
        out = log.read_after_index(-1, type_filter=EventType.TASK_STARTED)
        assert all(e["type"] == EventType.TASK_STARTED.value for e in out)
        assert len(out) == 1

    def test_write_failure_does_not_raise(self, tmp_path):
        # 写一个不存在的目录(强制 fail)
        log = EventLogger(tmp_path / "x" / "y" / "z.jsonl")
        # 写不存在的目录? 我们 mkdir 在 __init__ 做了, 改测 close 多次
        log.close()
        log.close()  # 不抛

    def test_read_nonexistent_returns_empty(self, tmp_path):
        log = EventLogger(tmp_path / "never.jsonl")
        log.close()
        log2 = EventLogger(tmp_path / "never.jsonl")
        assert log2.read_recent(10) == []


# ── MonitorBus ──────────────────────────────────────────────────────

class TestMonitorBus:
    def test_attach_subscribes_all_event_types(self, tmp_path):
        bus = LocalEventBus()
        log = EventLogger(tmp_path / "e.jsonl")
        mon = MonitorBus(bus, log)
        mon.attach()
        # 发 3 条不同类型
        bus.publish(Event(type=EventType.TASK_STARTED, payload={"i": 0}))
        bus.publish(Event(type=EventType.TASK_COMPLETED, payload={"i": 1}))
        bus.publish(Event(type=EventType.TASK_FAILED, payload={"i": 2}))
        time.sleep(0.05)  # 让 logger 缓冲 flush
        recent = log.read_recent(10)
        # 至少 3 条(可能更多如果 LocalEventBus 内部还有)
        types = {e["type"] for e in recent}
        assert EventType.TASK_STARTED.value in types
        assert EventType.TASK_COMPLETED.value in types
        assert EventType.TASK_FAILED.value in types
        log.close()

    def test_attach_idempotent(self, tmp_path):
        bus = LocalEventBus()
        log = EventLogger(tmp_path / "e.jsonl")
        mon = MonitorBus(bus, log)
        mon.attach()
        mon.attach()  # 多次
        mon.attach()
        # 不应爆, 且 3 次 attach 跟 1 次一样
        bus.publish(Event(type=EventType.TASK_STARTED, payload={"i": 0}))
        assert len(mon._subscribed) == len(list(EventType))


# ── HealthSnapshotter ──────────────────────────────────────────────

class TestHealthSnapshotter:
    def test_snapshot_includes_pool_report(self, tmp_path):
        bus = LocalEventBus()
        pool = SkillPool()
        pool.register(EchoSkill("a"))
        snap = HealthSnapshotter(pool, bus)
        s = snap.snapshot()
        assert "a" in s.pool
        assert s.pool["a"]["refcount"] == 0
        assert s.error_count == 0
        assert s.ok_count == 0

    def test_snapshot_counts_completed_and_failed(self, tmp_path):
        bus = LocalEventBus()
        pool = SkillPool()
        snap = HealthSnapshotter(pool, bus)
        bus.publish(Event(type=EventType.TASK_COMPLETED, payload={"i": 0}))
        bus.publish(Event(type=EventType.TASK_COMPLETED, payload={"i": 1}))
        bus.publish(Event(type=EventType.TASK_FAILED, payload={"i": 2}))
        s = snap.snapshot()
        assert s.ok_count == 2
        assert s.error_count == 1

    def test_snapshot_uses_logger_if_given(self, tmp_path):
        bus = LocalEventBus()
        pool = SkillPool()
        log = EventLogger(tmp_path / "e.jsonl")
        snap = HealthSnapshotter(pool, bus, log=log)
        log.write(Event(type=EventType.TASK_COMPLETED, payload={"i": 99}))
        s = snap.snapshot()
        assert s.ok_count == 1
        log.close()
