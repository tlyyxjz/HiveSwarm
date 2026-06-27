"""Brain 单元测试."""
from __future__ import annotations

import asyncio
import os

import pytest

from core.brain import Plan, SubTask
from layers.brain.planner import (
    LLMBrain,
    MockBrain,
    PlanParseError,
    _dict_to_plan,
    _extract_json,
)


# ── _extract_json ────────────────────────────────────────────────────

class TestExtractJson:
    def test_pure_json(self):
        assert _extract_json('{"a": 1}') == {"a": 1}

    def test_markdown_fenced(self):
        text = '```json\n{"a": 2}\n```'
        assert _extract_json(text) == {"a": 2}

    def test_embedded_in_prose(self):
        text = '好的,这是计划: {"a": 3, "b": [1, 2]}'
        assert _extract_json(text) == {"a": 3, "b": [1, 2]}

    def test_garbage_raises(self):
        with pytest.raises(PlanParseError):
            _extract_json("no json here at all")


# ── _dict_to_plan ─────────────────────────────────────────────────────

class TestDictToPlan:
    def test_minimal(self):
        d = {
            "task_id": "t1",
            "subtasks": [{"sub_id": "s1", "intent": "do"}],
        }
        p = _dict_to_plan(d, "orig")
        assert p.task_id == "t1"
        assert len(p.subtasks) == 1
        assert p.subtasks[0].sub_id == "s1"
        assert p.subtasks[0].required_skills == ()

    def test_full(self):
        d = {
            "task_id": "t2",
            "subtasks": [
                {
                    "sub_id": "s1",
                    "intent": "fetch",
                    "required_skills": ["scan"],
                    "depends_on": [],
                    "acceptance": "ok",
                }
            ],
            "rationale": "because",
        }
        p = _dict_to_plan(d, "orig")
        assert p.subtasks[0].required_skills == ("scan",)
        assert p.rationale == "because"

    def test_missing_task_id_raises(self):
        with pytest.raises(PlanParseError, match="task_id"):
            _dict_to_plan({"subtasks": []}, "orig")

    def test_missing_subtask_field_raises(self):
        with pytest.raises(PlanParseError, match="intent"):
            _dict_to_plan({"task_id": "t", "subtasks": [{"sub_id": "s1"}]}, "orig")


# ── MockBrain ────────────────────────────────────────────────────────

class TestMockBrain:
    def test_ppt_keyword(self):
        b = MockBrain()
        plan = asyncio.run(b.plan("帮我做一个 PPT"))
        assert any("数据" in s.intent for s in plan.subtasks)
        assert any("outline" in s.required_skills for s in plan.subtasks)
        # s2 依赖 s1
        s2 = next(s for s in plan.subtasks if s.sub_id == "s2")
        assert "s1" in s2.depends_on

    def test_scan_keyword(self):
        b = MockBrain()
        plan = asyncio.run(b.plan("扫描这个项目"))
        skills = {s for sub in plan.subtasks for s in sub.required_skills}
        assert "agentvet_l1" in skills

    def test_default_subtask_for_unknown(self):
        b = MockBrain()
        plan = asyncio.run(b.plan("hello"))
        assert len(plan.subtasks) == 1

    def test_decide_no_failure(self):
        b = MockBrain()
        plan = Plan(task_id="t", original_request="x")
        action, _ = asyncio.run(b.decide(plan, [{"ok": True}, {"ok": True}]))
        assert action == "continue"

    def test_decide_one_failure_switches(self):
        b = MockBrain()
        plan = Plan(task_id="t", original_request="x")
        action, _ = asyncio.run(b.decide(plan, [{"ok": False}]))
        assert action == "switch"

    def test_decide_three_failures_halts(self):
        b = MockBrain()
        plan = Plan(task_id="t", original_request="x")
        action, _ = asyncio.run(b.decide(plan, [{"ok": False}] * 3))
        assert action == "halt"


# ── LLMBrain (没 key 走 mock) ───────────────────────────────────────

class TestLLMBrainFallback:
    def test_no_key_uses_mock(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        b = LLMBrain("you are planner")
        plan = asyncio.run(b.plan("做一个 PPT"))
        # 走 mock,产出 4 个 subtask
        assert len(plan.subtasks) == 4
        assert "mock" in plan.rationale

    def test_with_key_uses_llm_path(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
        # monkeypatch llm_chat 跳过真实调用
        from layers.brain import planner as planner_mod

        def fake_chat(messages, model, **kw):
            return '{"task_id": "t1", "subtasks": [{"sub_id": "s1", "intent": "x", "required_skills": []}]}'

        monkeypatch.setattr(planner_mod, "llm_chat", fake_chat)
        b = LLMBrain("sys", model="gpt-test")
        plan = asyncio.run(b.plan("do x"))
        assert plan.task_id == "t1"
        assert len(plan.subtasks) == 1

    def test_llm_failure_falls_back_to_mock(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
        from layers.brain import planner as planner_mod

        def boom(messages, model, **kw):
            return "totally not json at all"

        monkeypatch.setattr(planner_mod, "llm_chat", boom)
        b = LLMBrain("sys", max_retries=1)
        plan = asyncio.run(b.plan("做一个 PPT"))
        # 重试用尽 → 降级 mock
        assert "mock" in plan.rationale
