"""RegressionGate — 回归闸 (榫卯 M2, T1.3; 设计稿 4.2.4).

回答评委心里那个问题: "你自动改来改去, 会不会越改越坏?"
重装配之后, 不只检查新断言, 还必须把此前所有已通过 (VERIFIED) 的断言
重跑一遍: 任何一条 从过变不过 → 标记有害修复 + 记账证伪 (复用
ledger.falsify 的只记账语义, 不抛异常). 指标"回归破坏率"的数据源.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from layers.contract.assertion import Assertion, AssertionStatus
from layers.contract.ledger import AssertionLedger

VerifyFn = Callable[[Assertion], bool]


@dataclass(frozen=True)
class RegressionReport:
    """gate 的结论. broken 非空 = 这次修复是有害修复, 必须回滚."""

    broken: tuple[tuple[str, str], ...] = ()  # (断言 aid, 失败详情)

    @property
    def needs_rollback(self) -> bool:
        return bool(self.broken)


class RegressionGate:
    """对账本内全部 VERIFIED 断言做回归复验. 纯逻辑, verify_fn 注入执行端."""

    def __init__(self, ledger: AssertionLedger, verify_fn: VerifyFn) -> None:
        self._ledger = ledger
        self._verify_fn = verify_fn

    def gate(self) -> RegressionReport:
        broken: list[tuple[str, str]] = []
        for a in self._ledger.list_assertions():
            if a.status is not AssertionStatus.VERIFIED:
                continue
            try:
                ok = bool(self._verify_fn(a))
            except Exception as e:  # 执行端炸了也算回归证据, 不让闸门自己挂掉
                broken.append((a.aid, f"verify_fn raised: {e!r}"))
                continue
            if not ok:
                broken.append((a.aid, f"regression: previously-passed {a.aid} now fails"))
        return RegressionReport(broken=tuple(broken))

    def rollback(self, report: RegressionReport, by: str = "regression-gate") -> tuple[str, ...]:
        """把被破坏的断言记账证伪 (只记账, 永不 raise). 返回实际证伪的 aid."""
        rolled_back: list[str] = []
        for aid, _detail in report.broken:
            if self._ledger.falsify(aid, observed_by=by) is not None:
                rolled_back.append(aid)
        return tuple(rolled_back)
