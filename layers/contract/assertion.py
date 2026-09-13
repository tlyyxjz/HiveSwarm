"""Assertion — 断言契约数据结构 (榫卯 M1, 见 docs/任务单_T11_断言契约层.md).

断言是"可机械判定的契约", 不是自然语言: validator_name 被白名单锁死在
layers/inspect/validator.py 的 6 种原语之内, 6 原语之外的约束在构造时即拒绝
——这是"杜绝假约束"的第一道闸 (第二道在 compiler).
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from layers.inspect.validator import (
    HasKeys,
    InRange,
    MaxLength,
    MinLength,
    NotEmpty,
    RegexMatch,
    Validator,
)

VALIDATOR_NAMES = (
    "not_empty",
    "min_length",
    "max_length",
    "regex_match",
    "in_range",
    "has_keys",
)


class AssertionKind(str, Enum):
    """断言种类: 前置 / 后置 / 不变量 (设计稿 4.1.1)."""

    PRE = "pre"
    POST = "post"
    INVARIANT = "invariant"


class AssertionOrigin(str, Enum):
    """断言来源."""

    LLM = "llm"
    HUMAN = "human"
    LEARNED = "learned"  # M3 验证阶梯归纳出来的


class AssertionStatus(str, Enum):
    """断言状态机: unverified → verified → (falsify 终态, 不回翻)."""

    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    FALSIFIED = "falsified"


class Assertion(BaseModel):
    """一条可机械判定的断言.

    frozen: 断言内容是账本里的既定事实, 改状态必须走 AssertionLedger
    (model_copy 换新实例), 不允许原地改.
    """

    model_config = ConfigDict(frozen=True)

    aid: str = Field(min_length=1, description="断言 id, 如 s12.pre.input_file")
    kind: AssertionKind
    subject: str = Field(min_length=1, description="字段路径, 如 output.count")
    predicate: str = Field(min_length=1, description="编译后的谓词串, 如 in:0,100")
    validator_name: str = Field(min_length=1, description="6 原语之一的小写名")
    validator_params: dict[str, Any] = Field(default_factory=dict)
    description: str = Field(default="", description="候选时的自然语言描述, 只作审计")
    level: int = Field(default=1, ge=0, le=3, description="验证等级 L0-L3")
    producer: str = Field(default="", description="产出这条断言的步骤/来源 id")
    origin: AssertionOrigin = AssertionOrigin.LLM
    status: AssertionStatus = AssertionStatus.UNVERIFIED

    @field_validator("validator_name")
    @classmethod
    def _name_must_be_primitive(cls, v: str) -> str:
        if v not in VALIDATOR_NAMES:
            raise ValueError(
                f"validator_name must be one of {VALIDATOR_NAMES}, got {v!r}"
            )
        return v

    def materialize(self) -> Validator:
        """把谓词还原成 validator.py 的原语实例 (执行端验证用)."""
        p = self.validator_params
        try:
            if self.validator_name == "not_empty":
                return NotEmpty()
            if self.validator_name == "min_length":
                return MinLength(int(p["n"]))
            if self.validator_name == "max_length":
                return MaxLength(int(p["n"]))
            if self.validator_name == "regex_match":
                return RegexMatch(str(p["pattern"]))
            if self.validator_name == "in_range":
                return InRange(float(p["low"]), float(p["high"]))
            if self.validator_name == "has_keys":
                return HasKeys(tuple(p["keys"]))
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(
                f"bad params for {self.validator_name!r}: {p!r} ({e})"
            ) from e
        raise ValueError(f"unknown validator_name: {self.validator_name!r}")  # pragma: no cover


def build_predicate(name: str, params: dict[str, Any]) -> str:
    """把 (原语名, 参数) 规范成谓词串. 编译器的唯一谓词格式来源."""
    if name == "not_empty":
        return "not_empty"
    if name == "min_length":
        return f"len>={int(params['n'])}"
    if name == "max_length":
        return f"len<={int(params['n'])}"
    if name == "regex_match":
        return f"match:{params['pattern']}"
    if name == "in_range":
        return f"in:{float(params['low'])},{float(params['high'])}"
    if name == "has_keys":
        return "keys:" + ",".join(params["keys"])
    raise ValueError(f"unknown validator_name: {name!r}")
