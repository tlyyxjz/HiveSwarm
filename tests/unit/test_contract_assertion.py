"""Assertion 模型测试 — 契约锁定: 6 原语白名单 / frozen / 状态默认 / materialize."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from layers.contract.assertion import (
    VALIDATOR_NAMES,
    Assertion,
    AssertionKind,
    AssertionOrigin,
    AssertionStatus,
    build_predicate,
)


def _mk(**over) -> Assertion:
    base = dict(
        aid="s1.pre.input_file",
        kind=AssertionKind.PRE,
        subject="input.file",
        predicate="len>=10",
        validator_name="min_length",
        validator_params={"n": 10},
    )
    base.update(over)
    return Assertion(**base)


class TestAssertionConstruction:
    def test_valid_defaults(self):
        a = _mk()
        assert a.status is AssertionStatus.UNVERIFIED
        assert a.level == 1
        assert a.origin is AssertionOrigin.LLM
        assert a.producer == ""
        assert a.description == ""

    def test_frozen_rejects_mutation(self):
        a = _mk()
        with pytest.raises(ValidationError):
            a.status = AssertionStatus.VERIFIED  # type: ignore[misc]

    def test_validator_name_whitelist(self):
        # 6 原语之外的名字在构造时即拒绝 — 杜绝假约束的第一道闸
        with pytest.raises(ValidationError, match="validator_name must be one of"):
            _mk(validator_name="is_polite")

    def test_all_six_names_accepted(self):
        for name in VALIDATOR_NAMES:
            assert _mk(validator_name=name).validator_name == name

    def test_invalid_kind_rejected(self):
        with pytest.raises(ValidationError):
            _mk(kind="middle")

    def test_level_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            _mk(level=4)
        with pytest.raises(ValidationError):
            _mk(level=-1)

    def test_empty_aid_and_subject_rejected(self):
        with pytest.raises(ValidationError):
            _mk(aid="")
        with pytest.raises(ValidationError):
            _mk(subject="")


class TestBuildPredicate:
    def test_all_six_formats(self):
        assert build_predicate("not_empty", {}) == "not_empty"
        assert build_predicate("min_length", {"n": 3}) == "len>=3"
        assert build_predicate("max_length", {"n": 5}) == "len<=5"
        assert build_predicate("regex_match", {"pattern": r"^\d{4}$"}) == r"match:^\d{4}$"
        assert build_predicate("in_range", {"low": 0, "high": 100}) == "in:0.0,100.0"
        assert build_predicate("has_keys", {"keys": ["a", "b"]}) == "keys:a,b"

    def test_unknown_name_raises(self):
        with pytest.raises(ValueError, match="unknown validator_name"):
            build_predicate("is_polite", {})

    def test_missing_param_raises(self):
        with pytest.raises(Exception):
            build_predicate("min_length", {})


class TestMaterialize:
    """materialize 必须还原成 validator.py 的原语实例 — 复用而非重造."""

    def test_roundtrip_all_six(self):
        from layers.inspect.validator import (
            HasKeys,
            InRange,
            MaxLength,
            MinLength,
            NotEmpty,
            RegexMatch,
        )

        cases = [
            ("not_empty", {}, NotEmpty, ""),
            ("min_length", {"n": 3}, MinLength, "ab"),  # len 2 < 3 → fail
            ("max_length", {"n": 2}, MaxLength, "abc"),
            ("regex_match", {"pattern": r"^\d+$"}, RegexMatch, "abc"),
            ("in_range", {"low": 0, "high": 10}, InRange, 11),
            ("has_keys", {"keys": ("k",)}, HasKeys, {}),
        ]
        for name, params, cls, bad_value in cases:
            a = _mk(
                validator_name=name,
                validator_params=params,
                predicate=build_predicate(name, params),
            )
            v = a.materialize()
            assert isinstance(v, cls), name
            assert v.check(bad_value).ok is False, name  # 原语行为真实生效

    def test_materialize_bad_params_raises_valueerror(self):
        a = _mk(validator_name="min_length", validator_params={})  # 缺 n
        with pytest.raises(ValueError, match="bad params"):
            a.materialize()
