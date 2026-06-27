"""Brain + Work 端到端集成 — 模拟用户说一句话到任务完成."""
from __future__ import annotations

import asyncio

from core.skill import Skill, SkillManifest
from layers.brain.planner import MockBrain
from layers.work.factory import AgentFactory
from layers.work.pool import SkillPool
from layers.work.transaction import TaskTransaction
from stub.bus_local import LocalEventBus


# 复用 test_work_e2e 里的 skill,加些常用的
class DataSkill(Skill):
    def __init__(self, name: str = "data_collect") -> None:
        super().__init__(SkillManifest(name=name, api_version="1.0"))

    def run(self, input_data: dict) -> dict:
        return {"ok": True, "by": self.manifest.name, "input": input_data}


def _make_pool_for_plan(bus: LocalEventBus, plan) -> SkillPool:
    pool = SkillPool(bus=bus)
    # 把 plan 里所有需要的 skill 都注册
    seen: set[str] = set()
    for sub in plan.subtasks:
        for s in sub.required_skills:
            if s not in seen:
                pool.register(DataSkill(s))
                seen.add(s)
    return pool


class TestBrainToWork:
    def test_ppt_request_full_flow(self):
        bus = LocalEventBus()
        brain = MockBrain()
        plan = asyncio.run(brain.plan("帮我做一个 PPT"))
        pool = _make_pool_for_plan(bus, plan)
        factory = AgentFactory(pool)

        with TaskTransaction(pool, factory, plan.task_id) as tx:
            for sub in plan.subtasks:
                tx.add(sub).run({})

        assert tx._result.all_ok
        assert tx._result.success_count == len(plan.subtasks)
        # 所有 refcount 归零
        for sub in plan.subtasks:
            for s in sub.required_skills:
                assert pool.health_report()[s]["refcount"] == 0

    def test_brain_decision_after_partial_failure(self):
        """brain 决策:跑一次,部分失败,decide 给 action."""
        bus = LocalEventBus()
        # 改 plan,让 s2 失败(s2 需要的 skill 不注册,subtask 直接抛装配错)
        brain = MockBrain()
        plan = asyncio.run(brain.plan("做一个 PPT"))
        # 只注册 s1 用的 skill
        pool = SkillPool(bus=bus)
        pool.register(DataSkill("data_collect"))  # s1 OK, s2 outline 缺失
        factory = AgentFactory(pool)

        with TaskTransaction(pool, factory, plan.task_id, abort_on_failure=True) as tx:
            for sub in plan.subtasks:
                tx.add(sub).run({})

        # 收集结果,给 brain 决策. 用 tx._result.results 直接拿 ok
        observations = [{"ok": r.ok, "sub_id": r.sub_id} for r in tx._result.results]
        action, reason = asyncio.run(brain.decide(plan, observations))
        # 至少有失败,decide 应该给 "switch"(1 次失败)或 "halt"(3+ 次)
        assert action in ("switch", "halt"), f"got {action!r}, reason={reason!r}"
        assert reason

    def test_decide_no_failures_returns_continue(self):
        bus = LocalEventBus()
        brain = MockBrain()
        plan = asyncio.run(brain.plan("hello"))  # 单 subtask
        observations = [{"ok": True}]
        action, _ = asyncio.run(brain.decide(plan, observations))
        assert action == "continue"

    def test_scan_request_uses_agentvet_skills(self):
        """Scan 关键词 → Plan 用 agentvet_* 技能."""
        bus = LocalEventBus()
        brain = MockBrain()
        plan = asyncio.run(brain.plan("扫描这个项目"))
        skills = {s for sub in plan.subtasks for s in sub.required_skills}
        assert "agentvet_l1" in skills
        assert "agentvet_l2" in skills
        # 注册这些 + 跑
        pool = _make_pool_for_plan(bus, plan)
        factory = AgentFactory(pool)
        with TaskTransaction(pool, factory, plan.task_id) as tx:
            for sub in plan.subtasks:
                tx.add(sub).run({})
        assert tx._result.all_ok
