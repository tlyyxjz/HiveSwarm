"""escalation — 验证阶梯 (榫卯 M3, T1.4; 设计稿 4.3).

直接回答 SAVeR 承认的 open problem: "a lack of adaptive verification depth".
机制: L1(事后观测) 的断言连续 N 次(promote_after≥3 默认)稳定通过 → 升 L2(事前拦截);
一旦被证伪 → 立刻降回 L1. 升降都发事件 (ASSERTION_ESCALATED / ASSERTION_DEGRADED /
ASSERTION_FALSIFIED), 可被 EventBus replay() 完整审计.

L0 不可验 (跳过); L3 不变量人工设定, 不自动升降, 仅在证伪时按降级规则回落 L1.
本模块是账本之上的薄状态机: 计数与状态迁移都委托 AssertionLedger.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.events import Event, EventType
from layers.contract.assertion import AssertionStatus
from layers.contract.ledger import AssertionLedger

Subscriber = object  # 类型提示用: Callable[[Event], None]


@dataclass(frozen=True)
class ObservationOutcome:
    """一次观测的结果. transition 是阶梯审计的关键字."""

    aid: str
    ok: bool
    transition: str  # promoted | degraded | falsified | none | not_verifiable | terminal_falsified
    level: int


class VerificationLadder:
    """验证阶梯: 系统持续提升"能看见多深"的能力 (适应能力的天花板)."""

    def __init__(
        self,
        ledger: AssertionLedger,
        *,
        promote_after: int = 3,
        emit: callable[[Event], None] | None = None,
    ) -> None:
        if promote_after < 1:
            raise ValueError("promote_after must be >= 1")
        self._ledger = ledger
        self._promote_after = promote_after
        self._emit = emit

    def _publish(self, et: EventType, payload: dict, ts: datetime | None) -> None:
        if self._emit is not None:
            # 显式传 ts, 不依赖 Event 默认值的类求值瑕疵 (方案 R7)
            self._emit(Event(type=et, payload=payload, ts=ts or datetime.now()))

    def observe(self, aid: str, ok: bool, ts: datetime | None = None) -> ObservationOutcome | None:
        """记录一次观测并驱动阶梯. 未知 aid → None (不打断执行流)."""
        if not self._ledger.has(aid):
            return None
        a = self._ledger.get(aid)
        if a.level == 0:
            return ObservationOutcome(aid, ok, "not_verifiable", a.level)
        if a.status is AssertionStatus.FALSIFIED:
            return ObservationOutcome(aid, ok, "terminal_falsified", a.level)

        if not ok:
            self._ledger.falsify(aid, observed_by="verification-ladder", ts=ts)
            self._publish(
                EventType.ASSERTION_FALSIFIED,
                {"aid": aid, "observed_by": "verification-ladder"},
                ts,
            )
            if a.level > 1:
                self._demote(aid, ts)
                return ObservationOutcome(aid, ok, "degraded", 1)
            return ObservationOutcome(aid, ok, "falsified", a.level)

        self._ledger.verify(aid)
        if a.level == 1 and self._ledger.pass_count(aid) >= self._promote_after:
            self._set_level(aid, 2, ts)
            self._publish(
                EventType.ASSERTION_ESCALATED,
                {"aid": aid, "from_level": 1, "to_level": 2},
                ts,
            )
            return ObservationOutcome(aid, ok, "promoted", 2)
        return ObservationOutcome(aid, ok, "none", a.level)

    # ── 内部 ────────────────────────────────────────────────────────────

    def _set_level(self, aid: str, level: int, ts: datetime | None) -> None:
        cur = self._ledger.get(aid)
        self._ledger._assertions[aid] = cur.model_copy(update={"level": level})

    def _demote(self, aid: str, ts: datetime | None) -> None:
        cur = self._ledger.get(aid)
        self._set_level(aid, 1, ts)
        self._publish(
            EventType.ASSERTION_DEGRADED,
            {"aid": aid, "from_level": cur.level, "to_level": 1},
            ts,
        )
