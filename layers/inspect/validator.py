"""Validator — 硬规则校验器, 单一职责: 输入 → 通过/失败 + 原因.

设计: 跟 Miku 桌宠里 EventHandlers 一样的"小函数, 单一职责"风格.
Validator 是纯函数, 不调 I/O, 不发事件, 容易测试.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ValidationResult:
    """单条校验结果. ok=False 时 error 必填."""

    ok: bool
    error: str = ""
    details: dict[str, Any] | None = None


class Validator(ABC):
    """校验器 ABC. 实现单一规则."""

    @abstractmethod
    def check(self, value: Any) -> ValidationResult:
        """跑这条规则."""


class NotEmpty(Validator):
    """值不能是 None / 空字符串 / 空 list / 空 dict."""

    def check(self, value: Any) -> ValidationResult:
        if value is None:
            return ValidationResult(ok=False, error="value is None")
        if isinstance(value, (str, list, dict, tuple)) and len(value) == 0:
            return ValidationResult(ok=False, error=f"empty {type(value).__name__}")
        return ValidationResult(ok=True)


class MinLength(Validator):
    """字符串 / 列表 / dict 长度 ≥ n."""

    def __init__(self, n: int) -> None:
        self.n = n

    def check(self, value: Any) -> ValidationResult:
        if not hasattr(value, "__len__"):
            return ValidationResult(ok=False, error="value has no length")
        if len(value) < self.n:
            return ValidationResult(ok=False, error=f"length {len(value)} < {self.n}")
        return ValidationResult(ok=True)


class MaxLength(Validator):
    """字符串 / 列表 / dict 长度 ≤ n."""

    def __init__(self, n: int) -> None:
        self.n = n

    def check(self, value: Any) -> ValidationResult:
        if not hasattr(value, "__len__"):
            return ValidationResult(ok=False, error="value has no length")
        if len(value) > self.n:
            return ValidationResult(ok=False, error=f"length {len(value)} > {self.n}")
        return ValidationResult(ok=True)


class RegexMatch(Validator):
    """字符串匹配正则."""

    def __init__(self, pattern: str, flags: int = 0) -> None:
        self.re = re.compile(pattern, flags)

    def check(self, value: Any) -> ValidationResult:
        if not isinstance(value, str):
            return ValidationResult(ok=False, error="value not a string")
        if not self.re.search(value):
            return ValidationResult(
                ok=False, error=f"value does not match pattern: {self.re.pattern}"
            )
        return ValidationResult(ok=True)


class InRange(Validator):
    """数字在 [low, high] 闭区间."""

    def __init__(self, low: float, high: float) -> None:
        self.low = low
        self.high = high

    def check(self, value: Any) -> ValidationResult:
        if not isinstance(value, (int, float)):
            return ValidationResult(ok=False, error="value not numeric")
        if not (self.low <= value <= self.high):
            return ValidationResult(
                ok=False, error=f"value {value} not in [{self.low}, {self.high}]"
            )
        return ValidationResult(ok=True)


class HasKeys(Validator):
    """dict 包含必需的 key."""

    def __init__(self, keys: tuple[str, ...]) -> None:
        self.keys = keys

    def check(self, value: Any) -> ValidationResult:
        if not isinstance(value, dict):
            return ValidationResult(ok=False, error="value not a dict")
        missing = [k for k in self.keys if k not in value]
        if missing:
            return ValidationResult(ok=False, error=f"missing keys: {missing}")
        return ValidationResult(ok=True)
