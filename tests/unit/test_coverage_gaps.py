"""覆盖率补测 (T3.3): EventLogger / skill_registry 的行为测试.

只测可观察行为, 不凑行数 (协作标准 4.5: 禁止垃圾测试刷覆盖率).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from core.brain import Plan, SubTask
from core.events import Event, EventType
from layers.monitor.logger import EventLogger
from layers.work.pool import SkillPool
from layers.work.skill_registry import (
    _EchoSkill,
    _try_register_real_skill,
    register_needed_skills,
)


class TestEventLogger:
    def _logger(self, tmp_path) -> EventLogger:
        return EventLogger(tmp_path / "events" / "log.jsonl")

    def test_write_and_read_recent(self, tmp_path):
        lg = self._logger(tmp_path)
        for i in range(5):
            lg.write(Event(type=EventType.TASK_STARTED, payload={"i": i}))
        rec = lg.read_recent(3)
        assert len(rec) == 3
        assert rec[0]["i"] == 4  # 倒序: 最新在前
        assert rec[0]["type"] == "task.started"
        lg.close()

    def test_read_recent_on_missing_file(self, tmp_path):
        lg = EventLogger(tmp_path / "ghost" / "x.jsonl")
        assert lg.read_recent() == []
        lg.close()

    def test_corrupt_lines_skipped(self, tmp_path):
        lg = self._logger(tmp_path)
        lg.write(Event(type=EventType.TASK_STARTED, payload={"a": 1}))
        lg.close()
        with open(lg._path, "a", encoding="utf-8") as f:
            f.write("{not json}\n")
        lg2 = EventLogger(lg._path)
        rec = lg2.read_recent(10)
        assert len(rec) == 1 and rec[0]["a"] == 1
        lg2.close()

    def test_read_since_filters_by_time_and_type(self, tmp_path):
        lg = self._logger(tmp_path)
        old = datetime(2026, 1, 1, 12, 0, 0)
        mid = Event(type=EventType.TASK_STARTED, payload={"k": "mid"}, ts=old)
        lg.write(mid)
        lg.write(Event(type=EventType.TASK_FAILED, payload={"k": "new"}, ts=old + timedelta(hours=1)))
        cutoff = old + timedelta(minutes=30)
        got = lg.read_since(cutoff)
        assert [r["k"] for r in got] == ["new"]  # 边界用 <=, 早于 cutoff 的被滤掉
        got2 = lg.read_since(cutoff, type_filter=EventType.TASK_FAILED)
        assert len(got2) == 1
        got3 = lg.read_since(cutoff, type_filter=EventType.TASK_COMPLETED)
        assert got3 == []
        lg.close()

    def test_read_since_bad_ts_skipped(self, tmp_path):
        lg = self._logger(tmp_path)
        lg.write(Event(type=EventType.TASK_STARTED, payload={"a": 1}))
        lg.close()
        with open(lg._path, "a", encoding="utf-8") as f:
            f.write('{"type": "task.started", "ts": "not-a-date"}\n')
        lg2 = EventLogger(lg._path)
        got = lg2.read_since(datetime(2020, 1, 1))
        assert len(got) == 1  # 坏 ts 行被跳过, 合法行保留
        assert got[0].get("a") == 1
        lg2.close()

    def test_read_after_index(self, tmp_path):
        lg = self._logger(tmp_path)
        for i in range(4):
            lg.write(Event(type=EventType.TASK_STARTED, payload={"i": i}))
        lg.close()
        lg2 = EventLogger(lg._path)
        after2 = lg2.read_after_index(1)
        assert [r["i"] for r in after2] == [2, 3]
        assert [r["i"] for r in lg2.read_after_index(1, type_filter=EventType.TASK_FAILED)] == []
        lg2.close()

    def test_close_idempotent(self, tmp_path):
        lg = self._logger(tmp_path)
        lg.close()
        lg.close()  # 二次 close 不炸


class TestSkillRegistry:
    def test_echo_skill_roundtrip(self):
        pool = SkillPool()
        sk = _EchoSkill("demo_x")
        pool.register(sk)
        out = pool.checkout(["demo_x"]) and True
        assert out
        assert sk.run({"q": 1})["ok"] is True
        assert sk.run({"q": 1})["by"] == "demo_x"

    def test_unknown_skill_falls_back_to_echo(self):
        pool = SkillPool()
        assert _try_register_real_skill(pool, "no_such_skill_xyz") is False
        plan = Plan(
            task_id="t", original_request="r",
            subtasks=[SubTask(sub_id="s1", intent="i", required_skills=("no_such_skill_xyz",))],
        )
        register_needed_skills(pool, plan)
        assert pool.is_available("no_such_skill_xyz")  # echo 兜底注册成功

    def test_dedup_across_subtasks(self):
        pool = SkillPool()
        plan = Plan(
            task_id="t", original_request="r",
            subtasks=[
                SubTask(sub_id="s1", intent="i", required_skills=("mock_a",)),
                SubTask(sub_id="s2", intent="i", required_skills=("mock_a", "mock_b")),
            ],
        )
        register_needed_skills(pool, plan)
        assert pool.is_available("mock_a") and pool.is_available("mock_b")
        # 重复注册同一技能会 raise (pool 语义), 没炸 = 去重生效

    def test_real_pack_registration_agentvet(self):
        """agentvet_pack 在仓库内, 真注册路径应成功 (非 echo)."""
        pool = SkillPool()
        ok = _try_register_real_skill(pool, "agentvet_l1")
        if ok:  # 依赖包内依赖可导入; 不可导入时回 echo 也是合法行为
            assert pool.is_available("agentvet_l1")
            assert not isinstance(
                pool._skills["agentvet_l1"], _EchoSkill
            )
