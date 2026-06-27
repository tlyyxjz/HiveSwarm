"""Inspect 层单元测试."""
from __future__ import annotations

import asyncio

import pytest

from layers.inspect.checker import Checker, CheckReport, ppt_result_checker, scan_result_checker
from layers.inspect.llm_judge import _rule_based_score, judge
from layers.inspect.validator import (
    HasKeys,
    InRange,
    MaxLength,
    MinLength,
    NotEmpty,
    RegexMatch,
    ValidationResult,
)


# ── Validator ────────────────────────────────────────────────────────

class TestNotEmpty:
    def test_none(self):
        assert NotEmpty().check(None).ok is False

    def test_empty_string(self):
        assert NotEmpty().check("").ok is False

    def test_empty_list(self):
        assert NotEmpty().check([]).ok is False

    def test_non_empty(self):
        assert NotEmpty().check("hi").ok is True
        assert NotEmpty().check([1]).ok is True


class TestMinMaxLength:
    def test_min(self):
        assert MinLength(3).check("abcd").ok is True
        assert MinLength(3).check("ab").ok is False

    def test_max(self):
        assert MaxLength(3).check("ab").ok is True
        assert MaxLength(3).check("abcd").ok is False

    def test_no_length_attr(self):
        assert MinLength(1).check(42).ok is False


class TestRegex:
    def test_match(self):
        assert RegexMatch(r"^hello").check("hello world").ok is True

    def test_no_match(self):
        r = RegexMatch(r"^hello").check("bye")
        assert r.ok is False
        assert "pattern" in r.error

    def test_not_string(self):
        assert RegexMatch(r".").check(123).ok is False


class TestInRange:
    def test_in(self):
        assert InRange(0, 10).check(5).ok is True
        assert InRange(0, 10).check(0).ok is True
        assert InRange(0, 10).check(10).ok is True

    def test_out(self):
        assert InRange(0, 10).check(11).ok is False
        assert InRange(0, 10).check(-1).ok is False

    def test_not_numeric(self):
        assert InRange(0, 10).check("x").ok is False


class TestHasKeys:
    def test_all_present(self):
        assert HasKeys(("a", "b")).check({"a": 1, "b": 2, "c": 3}).ok is True

    def test_missing(self):
        r = HasKeys(("a", "b")).check({"a": 1})
        assert r.ok is False
        assert "b" in r.error

    def test_not_dict(self):
        assert HasKeys(("a",)).check("not dict").ok is False


# ── Checker ─────────────────────────────────────────────────────────

class TestChecker:
    def test_empty_checker_passes(self):
        c = Checker("empty")
        report = c.check({})
        assert report.ok is True
        assert report.results == ()

    def test_one_rule_pass(self):
        c = Checker("t").add("x", NotEmpty())
        report = c.check({"x": "hi"})
        assert report.ok is True
        assert len(report.results) == 1

    def test_one_rule_fail(self):
        c = Checker("t").add("x", NotEmpty())
        report = c.check({"x": ""})
        assert report.ok is False
        assert "empty" in report.errors[0]

    def test_multiple_rules_short_circuit_report(self):
        c = Checker("t").add("a", NotEmpty()).add("b", MinLength(2))
        report = c.check({"a": "ok", "b": "x"})
        assert report.ok is False
        assert len(report.errors) == 1  # b 失败
        assert "length" in report.errors[0]

    def test_chained_add(self):
        c = Checker("t").add("a", NotEmpty()).add("b", MinLength(2))
        # 链式调用能跑
        assert len(c._rules) == 2


class TestPresetCheckers:
    def test_ppt_checker_passes(self):
        c = ppt_result_checker()
        assert c.check({"file": "out.pptx", "size_kb": 1024}).ok is True

    def test_ppt_checker_fails_missing_file(self):
        c = ppt_result_checker()
        assert c.check({"size_kb": 100}).ok is False

    def test_scan_checker_passes(self):
        c = scan_result_checker()
        # HasKeys 检查的是 findings 本身必须是 dict(代表单条结果)
        report = c.check({"findings": {"level": "high", "message": "x"}})
        assert report.ok is True

    def test_scan_checker_fails_missing_keys(self):
        c = scan_result_checker()
        # findings 是 dict 但缺 message
        report = c.check({"findings": {"level": "high"}})
        assert report.ok is False


# ── LLMJudge 降级 ───────────────────────────────────────────────────

class TestLLMJudgeFallback:
    def test_rule_based_empty_zero(self):
        assert _rule_based_score("") == 0.0

    def test_rule_based_short(self):
        # 太短不给加分
        assert _rule_based_score("hi") == 0.5

    def test_rule_based_good_length(self):
        s = "任务完成, success" * 3
        score = _rule_based_score(s)
        assert score > 0.5  # 长度加分 + 关键词加分

    def test_judge_no_key_uses_rule(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        s = asyncio.run(judge("任务完成 success", ""))
        assert s.is_llm is False
        assert 0.0 <= s.score <= 1.0
        assert "rule" in s.reason

    def test_judge_with_key_uses_llm(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
        from layers.inspect import llm_judge as judge_mod

        def fake_chat(messages, model, **kw):
            return "0.85"

        monkeypatch.setattr(judge_mod, "llm_chat", fake_chat)
        s = asyncio.run(judge("x", ""))
        assert s.is_llm is True
        assert s.score == 0.85

    def test_judge_score_clamped(self, monkeypatch):
        """LLM 返回 150 → clamp 到 1.0."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
        from layers.inspect import llm_judge as judge_mod

        def fake_chat(messages, model, **kw):
            return "150"

        monkeypatch.setattr(judge_mod, "llm_chat", fake_chat)
        s = asyncio.run(judge("x", ""))
        assert s.score == 1.0
