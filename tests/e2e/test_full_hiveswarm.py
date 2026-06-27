"""HiveSwarm 6 层端到端 demo — 用户一句话 → 任务完成.

数据流:
  user: "帮我做一个 PPT"  →  MockBrain.plan()  →  Plan
                                              ↓
  for sub in plan:
    TaskTransaction.add(sub).run(input)
      ↓
      Pool.checkout(skills)  →  Bundle
      Factory.assemble       →  Agent
      Agent.run              →  result
      Inspect.checker        →  report (or fail)
      Repair.fixer (if fail) →  re_assemble or halt
      MemoryStore.put        →  存结果
      Monitor bus.publish    →  事件流
      Pool.return_back       →  还
"""
from __future__ import annotations

import asyncio

import pytest

from core.brain import Plan
from core.events import EventType
from core.skill import Skill, SkillManifest
from layers.brain.planner import MockBrain
from layers.inspect.checker import ppt_result_checker
from layers.inspect.llm_judge import judge
from layers.memory.recall import recall_recent
from layers.memory.store import MemoryStore, MemoryTier
from layers.monitor.bus import MonitorBus
from layers.monitor.health import HealthSnapshotter
from layers.monitor.logger import EventLogger
from layers.repair.fixer import Fixer
from layers.work.factory import AgentFactory
from layers.work.pool import SkillPool
from layers.work.transaction import TaskTransaction
from stub.bus_local import LocalEventBus
from stub.store_sqlite import SQLiteStore


# ── Mock skill 们(把 PPT 流程跑通) ───────────────────────────────

class DataSkill(Skill):
    def __init__(self) -> None:
        super().__init__(SkillManifest(name="data_collect", api_version="1.0"))

    def run(self, input_data: dict) -> dict:
        topic = input_data.get("topic", "default")
        return {"topic": topic, "facts": [f"fact-{i}" for i in range(5)]}


class OutlineSkill(Skill):
    def __init__(self) -> None:
        super().__init__(SkillManifest(name="outline", api_version="1.0"))

    def run(self, input_data: dict) -> dict:
        facts = input_data.get("facts", [])
        return {"slides": [{"title": f"Slide {i+1}"} for i in range(len(facts) + 2)]}


class LayoutSkill(Skill):
    def __init__(self) -> None:
        super().__init__(SkillManifest(name="layout", api_version="1.0"))

    def run(self, input_data: dict) -> dict:
        return {"layouts": ["title", "content", "summary"]}


class ExportSkill(Skill):
    def __init__(self) -> None:
        super().__init__(SkillManifest(name="export", api_version="1.0"))

    def run(self, input_data: dict) -> dict:
        return {"file": "out.pptx", "size_kb": 2048, "layouts": ["title", "content"]}


def _setup_world(tmp_path):
    """6 层 + monitor + memory 全部构造好."""
    bus = LocalEventBus()
    log = EventLogger(tmp_path / "events.jsonl")
    mon = MonitorBus(bus, log)
    mon.attach()
    pool = SkillPool(bus=bus)
    for s in (DataSkill(), OutlineSkill(), LayoutSkill(), ExportSkill()):
        pool.register(s)
    factory = AgentFactory(pool)
    memory = MemoryStore(SQLiteStore(tmp_path / "mem.db"))
    health = HealthSnapshotter(pool, bus, log=log)
    return {
        "bus": bus, "log": log, "mon": mon, "pool": pool, "factory": factory,
        "memory": memory, "health": health, "brain": MockBrain(),
    }


# ── E2E ───────────────────────────────────────────────────────────

class TestFullHiveSwarmDemo:
    def test_user_request_to_ppt_completion(self, tmp_path):
        world = _setup_world(tmp_path)
        bus = world["bus"]
        memory = world["memory"]
        health = world["health"]

        # 1. 用户说话 → Brain 拆
        plan = asyncio.run(world["brain"].plan("帮我做一个 PPT"))
        assert isinstance(plan, Plan)
        assert len(plan.subtasks) >= 3

        # 2. 跑任务
        ctx = {"facts": ["fact-0", "fact-1", "fact-2", "fact-3", "fact-4"]}
        with TaskTransaction(world["pool"], world["factory"], plan.task_id) as tx:
            for sub in plan.subtasks:
                if "outline" in sub.required_skills:
                    inp = ctx
                elif "export" in sub.required_skills:
                    inp = {"layouts": ["title", "content"]}
                else:
                    inp = {"topic": "hiveswarm"}
                tx.add(sub).run(inp)

        # 3. 全部成功
        assert tx._result.all_ok
        assert tx._result.success_count == 4

        # 4. Inspect 校验最后的 export 结果
        last_result = tx._result.results[-1].result
        assert last_result is not None
        report = ppt_result_checker().check(last_result.get("result", {}))
        assert report.ok, f"export 校验失败: {report.errors}"

        # 5. Memory 存任务结果
        memory.put(MemoryTier.LONG, "last_task", {
            "task_id": plan.task_id,
            "result": last_result,
        })
        recs = recall_recent(memory, (MemoryTier.LONG,), limit=5)
        assert any(r["key"] == "last_task" for r in recs)

        # 6. Monitor 健康度快照: 至少 1 个借出 + 1 个归还
        snap = health.snapshot()
        events_types = {e["type"] for e in snap.recent_events}
        assert EventType.SKILL_CHECKED_OUT.value in events_types
        assert EventType.SKILL_RETURNED.value in events_types

        # 7. 所有 refcount 归零
        report_pool = world["pool"].health_report()
        for name in ("data_collect", "outline", "layout", "export"):
            assert report_pool[name]["refcount"] == 0

        world["log"].close()

    def test_failure_triggers_repair_proposal(self, tmp_path):
        """故意让 export 失败, 验证 inspect 失败 + repair 建议."""
        class BadExportSkill(Skill):
            def __init__(self) -> None:
                super().__init__(SkillManifest(name="export", api_version="1.0"))

            def run(self, input_data: dict) -> dict:
                return {"file": "out.pptx", "size_kb": 0}  # size_kb=0 触发 InRange 失败

        world = _setup_world(tmp_path)
        world["pool"].retire("export")
        world["pool"].register(BadExportSkill())  # 替换为坏版本

        from core.brain import SubTask
        st = SubTask(sub_id="s1", intent="export", required_skills=("export",))
        with TaskTransaction(world["pool"], world["factory"], "t1") as tx:
            tx.add(st).run({})

        last = tx._result.results[-1]
        # Agent.run 不会因为 size_kb=0 失败(它看的是 skill.run 是否抛错)
        # 但 inspect 会判定 size_kb=0 失败
        report = ppt_result_checker().check(last.result.get("result", {}))
        assert not report.ok
        # repair 提议
        fix = Fixer().propose(st, report)
        assert fix.action in ("re_assemble", "switch_skill", "halt")
        # size_kb 失败 → length 关键词不匹配, 走 re_assemble (fallback)
        # 但 0 不是 length, 看 "value 0 not in [1, 100000]" 含 "not" 不含 length
        # 所以应该是 re_assemble
        assert fix.action == "re_assemble"

        world["log"].close()

    def test_event_stream_records_full_lifecycle(self, tmp_path):
        """事件流: skill.checkout / return 一定出现."""
        world = _setup_world(tmp_path)
        bus = world["bus"]
        seen: list[EventType] = []
        for et in (EventType.SKILL_CHECKED_OUT, EventType.SKILL_RETURNED):
            bus.subscribe(et, lambda e, et=et: seen.append(et))

        # 跑 PPT 任务 (skill 已注册)
        plan = asyncio.run(world["brain"].plan("帮我做一个 PPT"))
        with TaskTransaction(world["pool"], world["factory"], plan.task_id) as tx:
            for sub in plan.subtasks:
                if "outline" in sub.required_skills:
                    inp = {"facts": [f"f{i}" for i in range(3)]}
                elif "export" in sub.required_skills:
                    inp = {"layouts": ["title", "content"]}
                else:
                    inp = {"topic": "x"}
                tx.add(sub).run(inp)

        # 必须出现借出和归还
        assert EventType.SKILL_CHECKED_OUT in seen
        assert EventType.SKILL_RETURNED in seen
        world["log"].close()
