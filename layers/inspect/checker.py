"""Checker — 多个 Validator 组合, 跑一次得所有结果.

设计: 跟 Miku 桌宠里的事件链一致 — 多个小函数串行/并行, 各自返回结果.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from layers.inspect.validator import (
    HasKeys,
    MinLength,
    NotEmpty,
    InRange,
    ValidationResult,
    Validator,
)


@dataclass(frozen=True)
class CheckReport:
    """一次检查的报告."""

    target: str  # 哪条数据
    ok: bool
    results: tuple[ValidationResult, ...] = field(default_factory=tuple)

    @property
    def errors(self) -> list[str]:
        return [r.error for r in self.results if not r.ok and r.error]


class Checker:
    """组合多个 Validator 跑检查."""

    def __init__(self, name: str = "default") -> None:
        self.name = name
        self._rules: list[tuple[str, Validator]] = []  # (field, validator)

    def add(self, field: str, validator: Validator) -> "Checker":
        """加一条规则: 对 data[field] 跑 validator."""
        self._rules.append((field, validator))
        return self  # 支持链式

    def check(self, data: dict[str, Any]) -> CheckReport:
        """跑所有规则, 出报告. 任一失败 ok=False."""
        results: list[ValidationResult] = []
        for field, v in self._rules:
            value = data.get(field)
            results.append(v.check(value))
        ok = all(r.ok for r in results)
        return CheckReport(target=self.name, ok=ok, results=tuple(results))


# 预设的常用 checker(开箱即用)
def ppt_result_checker() -> Checker:
    """校验"做 PPT"最终结果."""
    c = Checker("ppt_result")
    c.add("file", NotEmpty())
    c.add("size_kb", InRange(1, 100_000))
    return c


def scan_result_checker() -> Checker:
    """校验"扫描"结果."""
    c = Checker("scan_result")
    c.add("findings", MinLength(0))  # 至少 0 个(允许空)
    c.add("findings", HasKeys(("level", "message")))
    return c
