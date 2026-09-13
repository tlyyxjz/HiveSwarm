"""AssertionCompiler 测试 — 编译成功/拒绝路径 + 可编译率 (七指标之一的数据源)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from layers.contract.compiler import (
    AssertionCompiler,
    CandidateAssertion,
    CandidateConstraint,
)


def _cand(ctype: str, params: dict | None = None, subject: str = "output.count",
          kind: str = "post", description: str = "数量在 0-100 之间") -> CandidateAssertion:
    return CandidateAssertion(
        description=description,
        kind=kind,  # type: ignore[arg-type]
        subject=subject,
        producer="step-1",
        constraint=CandidateConstraint(type=ctype, params=params or {}),
    )


class TestCompileSuccess:
    def test_all_six_primitives_compile(self):
        c = AssertionCompiler()
        cases = [
            ("not_empty", {}, "not_empty"),
            ("min_length", {"n": 3}, "len>=3"),
            ("max_length", {"n": 5}, "len<=5"),
            ("regex_match", {"pattern": r"^\d{4}$"}, r"match:^\d{4}$"),
            ("in_range", {"low": 0, "high": 100}, "in:0.0,100.0"),
            ("has_keys", {"keys": ["level", "message"]}, "keys:level,message"),
        ]
        report = c.compile([_cand(t, p) for t, p, _ in cases])
        assert len(report.rejected) == 0
        assert report.compile_rate == 1.0
        for a, (_, _, pred) in zip(report.accepted, cases):
            assert a.predicate == pred
            assert a.producer == "step-1"
            assert a.description == "数量在 0-100 之间"  # 自然语言只作审计, 不参与判定

    def test_aid_auto_numbering(self):
        report = AssertionCompiler().compile(
            [_cand("not_empty", subject="f1"), _cand("min_length", {"n": 2}, subject="f2")]
        )
        a1, a2 = report.accepted
        assert a1.aid == "s1.post.f1"
        assert a2.aid == "s2.post.f2"


class TestCompileRejection:
    """凡不能映射到 6 原语的, 一律丢弃 — 这是"杜绝假约束"的关键."""

    def test_unmappable_type_dropped_not_raised(self):
        report = AssertionCompiler().compile([_cand("is_polite"), _cand("reads_well")])
        assert report.accepted == ()
        assert len(report.rejected) == 2
        assert all("unmappable" in r.reason for r in report.rejected)

    def test_missing_params_rejected(self):
        for ctype, params in [
            ("min_length", {}),  # 缺 n
            ("in_range", {"low": 0}),  # 缺 high
            ("regex_match", {}),  # 缺 pattern
            ("has_keys", {}),  # 缺 keys
        ]:
            report = AssertionCompiler().compile([_cand(ctype, params)])
            assert report.accepted == (), ctype
            assert len(report.rejected) == 1, ctype

    def test_bad_values_rejected(self):
        cases = [
            ("min_length", {"n": "three"}),  # 非整数
            ("min_length", {"n": True}),  # bool 冒充 int
            ("in_range", {"low": 10, "high": 0}),  # low > high
            ("regex_match", {"pattern": "(["}),  # 非法正则
            ("has_keys", {"keys": []}),  # 空 keys
            ("has_keys", {"keys": [1, 2]}),  # 非 str
        ]
        for ctype, params in cases:
            report = AssertionCompiler().compile([_cand(ctype, params)])
            assert report.accepted == (), (ctype, params)
            assert len(report.rejected) == 1, (ctype, params)
            assert report.rejected[0].reason  # 拒绝不许静默, 必须有原因

    def test_candidate_invalid_shape_raises_at_construction(self):
        with pytest.raises(ValidationError):
            CandidateAssertion(kind="post", subject="")  # 空 subject 进不来

    def test_mixed_batch_rate(self):
        cands = [
            _cand("in_range", {"low": 0, "high": 100}),
            _cand("is_polite"),  # 拒
            _cand("min_length", {"n": 1}),
            _cand("has_keys", {"keys": ["a"]}),
            _cand("is_short"),  # 拒
        ]
        report = AssertionCompiler().compile(cands)
        assert len(report.accepted) == 3
        assert len(report.rejected) == 2
        assert report.compile_rate == pytest.approx(3 / 5)


class TestCompileRateMetric:
    def test_empty_batch_rate_is_zero(self):
        assert AssertionCompiler().compile([]).compile_rate == 0.0

    def test_report_is_frozen(self):
        report = AssertionCompiler().compile([_cand("not_empty")])
        with pytest.raises(ValidationError):
            report.accepted = ()  # type: ignore[misc]
