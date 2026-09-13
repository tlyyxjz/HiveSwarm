"""AssertionCompiler — 候选断言编译器 (榫卯 M1, 见 docs/任务单_T11_断言契约层.md).

核心规则 (设计稿 4.1.2 决定 A): LLM 提的候选断言必须能映射到 6 种验证原语之一,
编不过的一律丢弃并记账拒绝原因 — 这是"杜绝假约束"的闸门.

不做自然语言解析: 候选约束是结构化的 (LLM 在真实系统里被要求产出结构化约束),
自然语言描述只作审计字段, 不参与判定 — 防止"翻译幻觉"进系统.
副产品: compile_rate 即七指标之一的"断言可编译率".
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from layers.contract.assertion import (
    Assertion,
    AssertionKind,
    AssertionOrigin,
    build_predicate,
)

# type → (validator_name, 必需参数). 表本身即"完备类型学"的一半:
# 不在表里的 type 一律拒绝, 没有兜底格子.
_COMPILE_TABLE: dict[str, str] = {
    "not_empty": "not_empty",
    "min_length": "min_length",
    "max_length": "max_length",
    "regex_match": "regex_match",
    "in_range": "in_range",
    "has_keys": "has_keys",
}


class CandidateConstraint(BaseModel):
    """LLM 产出的结构化约束候选. type 可以是任何字符串, 由编译器裁决."""

    model_config = ConfigDict(frozen=True)

    type: str
    params: dict[str, Any] = Field(default_factory=dict)


class CandidateAssertion(BaseModel):
    """一条候选断言: 结构化约束 + 审计性自然语言描述."""

    model_config = ConfigDict(frozen=True)

    description: str = ""
    kind: AssertionKind
    subject: str = Field(min_length=1)
    producer: str = ""
    origin: AssertionOrigin = AssertionOrigin.LLM
    constraint: CandidateConstraint


class Rejection(BaseModel):
    """一条被丢弃的候选 + 拒绝原因 (记账, 不静默)."""

    model_config = ConfigDict(frozen=True)

    subject: str
    constraint_type: str
    reason: str


class CompileReport(BaseModel):
    """一批候选的编译结果. compile_rate 即七指标之"断言可编译率"."""

    model_config = ConfigDict(frozen=True)

    accepted: tuple[Assertion, ...] = ()
    rejected: tuple[Rejection, ...] = ()

    @property
    def compile_rate(self) -> float:
        total = len(self.accepted) + len(self.rejected)
        return len(self.accepted) / total if total else 0.0


def _check_params(validator_name: str, params: dict[str, Any]) -> str | None:
    """参数合法性检查. 返回拒绝原因, None = 通过."""
    try:
        if validator_name == "not_empty":
            return None
        if validator_name in ("min_length", "max_length"):
            n = params["n"]
            if isinstance(n, bool) or not isinstance(n, int):
                return f"n must be int, got {n!r}"
            return None
        if validator_name == "regex_match":
            pattern = params["pattern"]
            if not isinstance(pattern, str):
                return f"pattern must be str, got {type(pattern).__name__}"
            re.compile(pattern)  # 非法正则在这里炸
            return None
        if validator_name == "in_range":
            low, high = params["low"], params["high"]
            for v in (low, high):
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    return f"low/high must be numeric, got {low!r}/{high!r}"
            if low > high:
                return f"low {low} > high {high}"
            return None
        if validator_name == "has_keys":
            keys = params["keys"]
            if not isinstance(keys, (list, tuple)) or not keys:
                return "keys must be a non-empty list/tuple"
            if not all(isinstance(k, str) for k in keys):
                return "keys must all be str"
            return None
    except KeyError as e:
        return f"missing required param {e}"
    except re.error as e:
        return f"invalid regex: {e}"
    return f"unknown validator_name {validator_name!r}"  # pragma: no cover


class AssertionCompiler:
    """把候选断言编译成 6 原语之一的 Assertion; 编不过丢弃, 不抛异常."""

    def compile_one(
        self, cand: CandidateAssertion, aid: str
    ) -> tuple[Assertion | None, Rejection | None]:
        """编译单条. 返回 (Assertion, None) 或 (None, Rejection)."""
        cname = cand.constraint.type
        vname = _COMPILE_TABLE.get(cname)
        if vname is None:
            return None, Rejection(
                subject=cand.subject,
                constraint_type=cname,
                reason=f"unmappable primitive: {cname!r} (not in 6-validator table)",
            )
        bad = _check_params(vname, cand.constraint.params)
        if bad is not None:
            return None, Rejection(
                subject=cand.subject, constraint_type=cname, reason=bad
            )
        try:
            predicate = build_predicate(vname, cand.constraint.params)
        except (KeyError, TypeError, ValueError) as e:
            return None, Rejection(
                subject=cand.subject, constraint_type=cname, reason=f"bad params: {e}"
            )
        assertion = Assertion(
            aid=aid,
            kind=cand.kind,
            subject=cand.subject,
            predicate=predicate,
            validator_name=vname,
            validator_params=dict(cand.constraint.params),
            description=cand.description,
            producer=cand.producer,
            origin=cand.origin,
        )
        return assertion, None

    def compile(
        self, candidates: list[CandidateAssertion], *, aid_prefix: str = "s"
    ) -> CompileReport:
        """编译一批. aid 自动编号: {prefix}{序号}.{kind}.{subject}."""
        accepted: list[Assertion] = []
        rejected: list[Rejection] = []
        for i, cand in enumerate(candidates, start=1):
            aid = f"{aid_prefix}{i}.{cand.kind.value}.{cand.subject}"
            a, r = self.compile_one(cand, aid)
            if a is not None:
                accepted.append(a)
            else:
                rejected.append(r)  # type: ignore[arg-type]
        return CompileReport(accepted=tuple(accepted), rejected=tuple(rejected))
