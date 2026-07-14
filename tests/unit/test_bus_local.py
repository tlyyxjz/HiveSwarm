"""LocalEventBus 单测 — 进程内 pub/sub, 通信命脉."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta

import pytest

from core.events import Event, EventType
from stub.bus_local import LocalEventBus


# ── 基本 pub/sub ─────────────────────────────────────────────

class TestPubSub:
    def test_publish_triggers_subscriber(self) -> None:
        bus = LocalEventBus()
        received: list[Event] = []
        bus.subscribe(EventType.TASK_STARTED, lambda e: received.append(e))
        bus.publish(Event(type=EventType.TASK_STARTED, payload={"task_id": "t-1"}))
        assert len(received) == 1
        assert received[0].payload["task_id"] == "t-1"

    def test_multiple_subscribers_all_triggered(self) -> None:
        bus = LocalEventBus()
        r1, r2 = [], []
        bus.subscribe(EventType.TASK_STARTED, lambda e: r1.append(e))
        bus.subscribe(EventType.TASK_STARTED, lambda e: r2.append(e))
        bus.publish(Event(type=EventType.TASK_STARTED, payload={"x": 1}))
        bus.publish(Event(type=EventType.TASK_STARTED, payload={"x": 2}))
        assert len(r1) == 2
        assert len(r2) == 2

    def test_subscriber_only_gets_subscribed_type(self) -> None:
        bus = LocalEventBus()
        got_started: list[Event] = []
        got_completed: list[Event] = []
        bus.subscribe(EventType.TASK_STARTED, lambda e: got_started.append(e))
        bus.subscribe(EventType.TASK_COMPLETED, lambda e: got_completed.append(e))
        bus.publish(Event(type=EventType.TASK_STARTED, payload={}))
        bus.publish(Event(type=EventType.TASK_COMPLETED, payload={}))
        assert len(got_started) == 1
        assert len(got_completed) == 1

    def test_unsubscribe_stops_callback(self) -> None:
        bus = LocalEventBus()
        received: list[Event] = []
        sub_id = bus.subscribe(EventType.TASK_STARTED, lambda e: received.append(e))
        bus.publish(Event(type=EventType.TASK_STARTED, payload={}))
        bus.unsubscribe(EventType.TASK_STARTED, sub_id)
        bus.publish(Event(type=EventType.TASK_STARTED, payload={}))
        assert len(received) == 1

    def test_unsubscribe_unknown_id_no_error(self) -> None:
        bus = LocalEventBus()
        bus.unsubscribe(EventType.TASK_STARTED, 99999)  # 不报错


# ── 异常隔离 ──────────────────────────────────────────────────

class TestErrorIsolation:
    def test_subscriber_exception_does_not_block_publish(self) -> None:
        bus = LocalEventBus()
        received_after: list[Event] = []

        def bad(_e: Event) -> None:
            raise RuntimeError("subscriber crash")

        bus.subscribe(EventType.TASK_STARTED, bad)
        bus.subscribe(EventType.TASK_STARTED, lambda e: received_after.append(e))
        # bad() 抛异常, 但 publish 应继续调第二个 subscriber
        bus.publish(Event(type=EventType.TASK_STARTED, payload={}))
        assert len(received_after) == 1

    def test_one_bad_subscriber_does_not_affect_others(self) -> None:
        bus = LocalEventBus()
        r1, r2 = [], []

        def bad(_e: Event) -> None:
            raise ValueError("boom")

        bus.subscribe(EventType.TASK_FAILED, bad)
        bus.subscribe(EventType.TASK_FAILED, lambda e: r1.append(e))
        bus.subscribe(EventType.TASK_FAILED, lambda e: r2.append(e))
        bus.publish(Event(type=EventType.TASK_FAILED, payload={"x": 1}))
        bus.publish(Event(type=EventType.TASK_FAILED, payload={"x": 2}))
        assert len(r1) == 2
        assert len(r2) == 2


# ── recent / replay ──────────────────────────────────────────

class TestRecentAndReplay:
    def test_recent_returns_dicts(self) -> None:
        bus = LocalEventBus()
        for i in range(5):
            bus.publish(Event(type=EventType.TASK_STARTED, payload={"i": i}))
        out = bus.recent(3)
        assert len(out) == 3
        assert isinstance(out[0], dict)
        assert out[-1]["i"] == 4  # 最新在最后

    def test_recent_filter_by_type(self) -> None:
        bus = LocalEventBus()
        bus.publish(Event(type=EventType.TASK_STARTED, payload={}))
        bus.publish(Event(type=EventType.TASK_COMPLETED, payload={}))
        bus.publish(Event(type=EventType.TASK_STARTED, payload={}))
        out = bus.recent(10, type_=EventType.TASK_STARTED)
        assert len(out) == 2
        assert all(e["type"] == "task.started" for e in out)

    def test_replay_returns_all_by_default(self) -> None:
        bus = LocalEventBus()
        for i in range(3):
            bus.publish(Event(type=EventType.TASK_STARTED, payload={"i": i}))
        assert len(bus.replay()) == 3

    def test_replay_filter_since_ts(self) -> None:
        bus = LocalEventBus()
        bus.publish(Event(type=EventType.TASK_STARTED, payload={"phase": "before"}))
        cutoff = datetime.now()
        bus.publish(Event(type=EventType.TASK_STARTED, payload={"phase": "after"}))
        out = bus.replay(since_ts=cutoff)
        assert all(e.payload["phase"] == "after" for e in out)


# ── max_log 截断 ────────────────────────────────────────────

class TestMaxLog:
    def test_log_truncated_to_max(self) -> None:
        bus = LocalEventBus(max_log=5)
        for i in range(10):
            bus.publish(Event(type=EventType.TASK_STARTED, payload={"i": i}))
        # 只保留最后 5 条
        assert len(bus.replay()) == 5
        # 最早的 (i=0..4) 应该被丢弃
        replayed = bus.replay()
        assert [e.payload["i"] for e in replayed] == [5, 6, 7, 8, 9]

    def test_default_max_log_is_large(self) -> None:
        bus = LocalEventBus()
        assert bus._max_log == 10000


# ── 并发 ─────────────────────────────────────────────────────

class TestConcurrency:
    def test_concurrent_publish_all_received(self) -> None:
        bus = LocalEventBus()
        received: list[int] = []
        lock = threading.Lock()

        def cb(e: Event) -> None:
            with lock:
                received.append(e.payload["i"])

        bus.subscribe(EventType.TASK_STARTED, cb)

        def worker(idx: int) -> None:
            for j in range(10):
                bus.publish(Event(type=EventType.TASK_STARTED, payload={"i": idx * 100 + j}))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(received) == 40

    def test_publish_blocks_until_slow_subscriber(self) -> None:
        """LocalEventBus 设计 = 同步派发: publish 会等 subscriber 完成.
        跟 Kafka 异步 fire-and-forget 不同, MVP 用同步更易推理."""
        import time as _time
        bus = LocalEventBus()
        bus.subscribe(EventType.TASK_STARTED, lambda _e: _time.sleep(0.05))
        t0 = _time.time()
        bus.publish(Event(type=EventType.TASK_STARTED, payload={}))
        elapsed = _time.time() - t0
        # 至少等 subscriber 50ms
        assert elapsed >= 0.04


# ── 边界 ─────────────────────────────────────────────────────

class TestEdgeCases:
    def test_subscribe_to_type_with_no_publish(self) -> None:
        bus = LocalEventBus()
        received: list[Event] = []
        bus.subscribe(EventType.PAUSE_POINT, lambda e: received.append(e))
        bus.publish(Event(type=EventType.TASK_STARTED, payload={}))
        assert received == []

    def test_publish_with_no_subscribers(self) -> None:
        bus = LocalEventBus()
        bus.publish(Event(type=EventType.TASK_STARTED, payload={}))
        assert len(bus.replay()) == 1

    def test_recent_zero(self) -> None:
        bus = LocalEventBus()
        assert bus.recent(0) == []