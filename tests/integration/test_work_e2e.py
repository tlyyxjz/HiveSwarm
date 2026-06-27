"""Work 层端到端集成测试 — 模拟"做一个 PPT"完整流程.

4 个 skill: data_collect / outline / layout / export
4 个 subtask: 采数据 → 大纲 → 排版 → 导出
验证: 全成功 + 借还计数归零 + 事件流顺序对 + abort 行为.
"""
from __future__ import annotations

from core.brain import SubTask
from core.events import EventType
from core.skill import Skill, SkillManifest
from layers.work.factory import AgentFactory
from layers.work.pool import SkillPool
from layers.work.transaction import TaskTransaction
from stub.bus_local import LocalEventBus


# ── 假 skill 们 ──────────────────────────────────────────────────────

class DataCollectSkill(Skill):
    def __init__(self) -> None:
        super().__init__(SkillManifest(name="data_collect", api_version="1.0"))

    def run(self, input_data: dict) -> dict:
        return {"topic": input_data.get("topic", ""), "facts": ["A", "B", "C"]}


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
        return {"file": "out.pptx", "size_kb": 1024}


def _make_ppt_pool(bus: LocalEventBus) -> SkillPool:
    pool = SkillPool(bus=bus)
    pool.register(DataCollectSkill())
    pool.register(OutlineSkill())
    pool.register(LayoutSkill())
    pool.register(ExportSkill())
    return pool


# ── 集成测试 ────────────────────────────────────────────────────────

class TestPPTPipeline:
    def test_full_ppt_pipeline_succeeds(self):
        bus = LocalEventBus()
        pool = _make_ppt_pool(bus)
        factory = AgentFactory(pool)
        st_data = SubTask(sub_id="s1", intent="采集", required_skills=("data_collect",))
        st_outline = SubTask(sub_id="s2", intent="大纲", required_skills=("outline",))
        st_layout = SubTask(sub_id="s3", intent="排版", required_skills=("layout",))
        st_export = SubTask(sub_id="s4", intent="导出", required_skills=("export",))

        with TaskTransaction(pool, factory, "ppt-task-001") as tx:
            tx.add(st_data).run({"topic": "hiveswarm"})
            tx.add(st_outline).run({})  # 实际生产里上一轮的 result 注入
            tx.add(st_layout).run({})
            tx.add(st_export).run({})

        # 4/4 全成功
        assert tx._result.success_count == 4
        assert tx._result.fail_count == 0
        assert tx._result.all_ok is True
        # 所有 refcount 归零
        report = pool.health_report()
        for name in ("data_collect", "outline", "layout", "export"):
            assert report[name]["refcount"] == 0

    def test_event_order_correct(self):
        bus = LocalEventBus()
        pool = _make_ppt_pool(bus)
        factory = AgentFactory(pool)
        events: list[EventType] = []
        for et in (
            EventType.SKILL_CHECKED_OUT,
            EventType.SKILL_RETURNED,
        ):
            bus.subscribe(et, lambda e: events.append(e.type))

        st = SubTask(sub_id="s1", intent="采", required_skills=("data_collect",))
        with TaskTransaction(pool, factory, "t1") as tx:
            tx.add(st).run({"topic": "x"})

        # 期望: checkout -> return
        assert events == [EventType.SKILL_CHECKED_OUT, EventType.SKILL_RETURNED]

    def test_event_count_matches_borrows(self):
        """跑 4 个 subtask,各 1 借 1 还,共 4 checkout + 4 return."""
        bus = LocalEventBus()
        pool = _make_ppt_pool(bus)
        factory = AgentFactory(pool)
        events: list[EventType] = []
        for et in (
            EventType.SKILL_CHECKED_OUT,
            EventType.SKILL_RETURNED,
        ):
            bus.subscribe(et, lambda e: events.append(e.type))

        subtasks = [
            SubTask(sub_id=f"s{i}", intent="do", required_skills=(name,))
            for i, name in enumerate(("data_collect", "outline", "layout", "export"))
        ]
        with TaskTransaction(pool, factory, "t1") as tx:
            for st in subtasks:
                tx.add(st).run({})

        checkouts = sum(1 for e in events if e == EventType.SKILL_CHECKED_OUT)
        returns = sum(1 for e in events if e == EventType.SKILL_RETURNED)
        assert checkouts == 4
        assert returns == 4

    def test_partial_failure_aborts_and_releases_all(self):
        """中间一个炸了,前面的还,后面的不借."""
        class BrokenOutline(Skill):
            def __init__(self) -> None:
                super().__init__(SkillManifest(name="outline", api_version="1.0"))

            def run(self, input_data):
                raise RuntimeError("outline crashed")

        bus = LocalEventBus()
        pool = SkillPool(bus=bus)
        pool.register(DataCollectSkill())
        pool.register(BrokenOutline())
        pool.register(LayoutSkill())
        factory = AgentFactory(pool)

        st_data = SubTask(sub_id="s1", intent="d", required_skills=("data_collect",))
        st_outline = SubTask(sub_id="s2", intent="o", required_skills=("outline",))
        st_layout = SubTask(sub_id="s3", intent="l", required_skills=("layout",))

        with TaskTransaction(pool, factory, "t1", abort_on_failure=True) as tx:
            tx.add(st_data).run({})
            tx.add(st_outline).run({})
            tx.add(st_layout).run({})  # 跳过

        assert tx._result.aborted
        assert tx._result.success_count == 1
        # 所有 refcount 归零(layout 没被借,outline 还了,data_collect 还了)
        for name in ("data_collect", "outline", "layout"):
            assert pool.health_report().get(name, {}).get("refcount", 0) == 0
