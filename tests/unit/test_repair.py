"""Repair 层单元测试."""
from __future__ import annotations

import pytest

from core.brain import SubTask
from layers.inspect.checker import CheckReport, Checker
from layers.inspect.validator import NotEmpty, RegexMatch
from layers.repair.fixer import Fixer, FixPlan
from layers.repair.re_assembler import ReAssembler
from layers.repair.strategy_table import RepairAction, StrategyTable


# ── StrategyTable ───────────────────────────────────────────────────

class TestStrategyTable:
    def test_default_table_matches_known(self):
        t = StrategyTable()
        assert t.lookup("length too short") == "switch_skill"
        assert t.lookup("pattern not matched") == "re_assemble"
        assert t.lookup("score too low") == "switch_skill"
        assert t.lookup("timeout occurred") == "halt"
        assert t.lookup("permission denied") == "halt"

    def test_unknown_error_uses_fallback(self):
        t = StrategyTable()
        assert t.lookup("weird error xyz") == "re_assemble"

    def test_custom_override(self):
        t = StrategyTable(table={"length": "halt"})
        assert t.lookup("length problem") == "halt"

    def test_explain_returns_action_with_reason(self):
        t = StrategyTable()
        a = t.explain("length problem")
        assert isinstance(a, RepairAction)
        assert a.name == "switch_skill"
        assert "length" in a.reason


# ── Fixer ───────────────────────────────────────────────────────────

def _ppt_subtask() -> SubTask:
    return SubTask(
        sub_id="s1", intent="做 PPT", required_skills=("ppt_gen",), acceptance="has file"
    )


def _fail_report() -> CheckReport:
    return CheckReport(
        target="ppt_result",
        ok=False,
        results=(
            NotEmpty().check(None),  # fail: value is None
        ),
    )


class TestFixer:
    def test_propose_returns_plan(self):
        f = Fixer()
        plan = f.propose(_ppt_subtask(), _fail_report())
        assert isinstance(plan, FixPlan)
        assert plan.target_subtask == "s1"

    def test_unknown_error_defaults_re_assemble(self):
        f = Fixer()
        plan = f.propose(_ppt_subtask(), _fail_report())
        # "value is None" 不匹配任何关键词, 走 re_assemble
        assert plan.action == "re_assemble"

    def test_known_error_picks_action(self):
        f = Fixer()
        # 构造一个 length 错误的报告 (MinLength 失败 → error 含 "length < N")
        from layers.inspect.validator import MinLength
        c = Checker("x").add("x", MinLength(10))
        report = c.check({"x": "short"})  # 长度 5 < 10
        assert not report.ok
        assert any("length" in e for e in report.errors)
        plan = f.propose(_ppt_subtask(), report)
        assert plan.action == "switch_skill"
        assert plan.new_skills == ()


# ── ReAssembler ─────────────────────────────────────────────────────

class TestReAssembler:
    def test_reassemble_switch_skill(self):
        ra = ReAssembler()
        plan = FixPlan(
            action="switch_skill",
            target_subtask="s1",
            reason="r",
            new_skills=("ppt_v2",),
        )
        new = ra.reassemble(_ppt_subtask(), plan)
        assert new.required_skills == ("ppt_v2",)
        assert new.sub_id == "s1"  # 其它不变

    def test_reassemble_change_intent(self):
        ra = ReAssembler()
        plan = FixPlan(
            action="re_assemble",
            target_subtask="s1",
            reason="r",
            new_intent="换种思路做 PPT",
        )
        new = ra.reassemble(_ppt_subtask(), plan)
        assert new.intent == "换种思路做 PPT"

    def test_reassemble_halt_returns_original(self):
        ra = ReAssembler()
        plan = FixPlan(action="halt", target_subtask="s1", reason="r")
        new = ra.reassemble(_ppt_subtask(), plan)
        assert new == _ppt_subtask()

    def test_reassemble_no_skills_returns_original(self):
        """switch 但没给 new_skills, 不动."""
        ra = ReAssembler()
        plan = FixPlan(action="switch_skill", target_subtask="s1", reason="r", new_skills=())
        new = ra.reassemble(_ppt_subtask(), plan)
        assert new == _ppt_subtask()
