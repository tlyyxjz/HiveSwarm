"""AgentFactory 单元测试."""
from __future__ import annotations

import asyncio

import pytest

from core.brain import SubTask
from core.skill import Skill, SkillHealth, SkillManifest
from layers.work.factory import AgentAlreadyDestroyedError, AgentFactory, TempAgent
from layers.work.pool import SkillPool


class EchoSkill(Skill):
    def __init__(self, name: str = "echo") -> None:
        super().__init__(SkillManifest(name=name, api_version="1.0"))
        self.calls: list[dict] = []

    def run(self, input_data: dict) -> dict:
        self.calls.append(input_data)
        return {"echo": input_data, "ts": 1.0}


class FailSkill(Skill):
    def __init__(self, name: str = "fail") -> None:
        super().__init__(SkillManifest(name=name, api_version="1.0"))

    def run(self, input_data: dict) -> dict:
        raise RuntimeError("skill boom")


# ── TempAgent ──────────────────────────────────────────────────────────

class TestTempAgent:
    def test_run_uses_default_skill_when_none_specified(self):
        s = EchoSkill("echo")
        a = TempAgent([s])
        r = asyncio.run(a.run({"intent": "test", "input": {"x": 1}}))
        assert r["ok"] is True
        assert r["skill"] == "echo"
        assert s.calls == [{"x": 1}]

    def test_run_uses_explicit_skill(self):
        a_skill = EchoSkill("a")
        b_skill = EchoSkill("b")
        a = TempAgent([a_skill, b_skill])
        r = asyncio.run(a.run({"skill": "b", "input": {"k": "v"}}))
        assert r["skill"] == "b"
        assert b_skill.calls == [{"k": "v"}]
        assert a_skill.calls == []  # a 没被调

    def test_run_after_destroy_raises(self):
        s = EchoSkill()
        a = TempAgent([s])
        a.destroy()
        with pytest.raises(AgentAlreadyDestroyedError):
            asyncio.run(a.run({"input": {}}))

    def test_run_returns_error_dict_when_skill_missing(self):
        s = EchoSkill("only")
        a = TempAgent([s])
        r = asyncio.run(a.run({"skill": "nope", "input": {}}))
        assert r["ok"] is False
        assert "nope" in r["error"]

    def test_run_catches_skill_exception(self):
        f = FailSkill()
        a = TempAgent([f])
        r = asyncio.run(a.run({"input": {}}))
        assert r["ok"] is False
        assert "boom" in r["error"]

    def test_destroy_idempotent(self):
        s = EchoSkill()
        a = TempAgent([s])
        a.destroy()
        a.destroy()  # 不抛

    def test_agent_id_unique_by_default(self):
        a1 = TempAgent([EchoSkill()])
        a2 = TempAgent([EchoSkill()])
        assert a1.agent_id != a2.agent_id
        assert a1.agent_id.startswith("agent-")


# ── AgentFactory + Pool 集成 ──────────────────────────────────────────

class TestFactoryIntegration:
    def _make_pool(self) -> SkillPool:
        pool = SkillPool()
        pool.register(EchoSkill("a"))
        pool.register(EchoSkill("b"))
        return pool

    def test_assemble_returns_agent_and_borrowed(self):
        pool = self._make_pool()
        factory = AgentFactory(pool)
        subtask = SubTask(sub_id="s1", intent="do", required_skills=("a", "b"))
        agent, borrowed = factory.assemble(subtask)
        assert isinstance(agent, TempAgent)
        assert agent.skills == ["a", "b"]
        # borrow 已生效
        assert pool.health_report()["a"]["refcount"] == 1
        assert pool.health_report()["b"]["refcount"] == 1
        # 用完归还
        with borrowed:
            pass
        assert pool.health_report()["a"]["refcount"] == 0
        assert pool.health_report()["b"]["refcount"] == 0

    def test_assemble_and_run_one_shot(self):
        pool = self._make_pool()
        factory = AgentFactory(pool)
        subtask = SubTask(sub_id="s1", intent="do", required_skills=("a",))
        result = factory.assemble_and_run(subtask, {"x": 42})
        assert result["ok"] is True
        assert result["skill"] == "a"
        # 跑完已归还
        assert pool.health_report()["a"]["refcount"] == 0

    def test_assemble_and_run_on_failure_still_returns_skill(self):
        """skill 抛异常时,借用也必须归还(没泄漏)."""
        pool = SkillPool()
        pool.register(FailSkill("f"))
        factory = AgentFactory(pool)
        subtask = SubTask(sub_id="s1", intent="do", required_skills=("f",))
        result = factory.assemble_and_run(subtask, {})
        assert result["ok"] is False
        # 归还了
        assert pool.health_report()["f"]["refcount"] == 0

    def test_assemble_missing_skill_raises_without_leak(self):
        """装配时缺技能, 已借的不能泄漏."""
        pool = self._make_pool()
        factory = AgentFactory(pool)
        # 任务需要 a, b, c — 但 c 没注册
        subtask = SubTask(sub_id="s1", intent="do", required_skills=("a", "b", "c"))
        with pytest.raises(KeyError, match="c"):
            factory.assemble(subtask)
        # a, b 都没泄漏
        assert pool.health_report()["a"]["refcount"] == 0
        assert pool.health_report()["b"]["refcount"] == 0

    def test_multiple_subtasks_serial(self):
        """多个 subtask 串行,每次都借/还,refcount 始终在 0/1 波动."""
        pool = self._make_pool()
        factory = AgentFactory(pool)
        for i in range(5):
            st = SubTask(sub_id=f"s{i}", intent="do", required_skills=("a",))
            factory.assemble_and_run(st, {"i": i})
        assert pool.health_report()["a"]["refcount"] == 0
        assert pool.health_report()["b"]["refcount"] == 0
