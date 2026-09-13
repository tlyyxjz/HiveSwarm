"""AssertionLedger — 断言账本 + 依赖图 (榫卯 M1, 见 docs/任务单_T11_断言契约层.md).

设计稿 4.1.4 决定 C: 账本是 typed dependency graph, 不是日志.
四种边 (从溯源七关系里裁剪): derive / depends_on / invalidates / trigger.

关键行为: falsify() 只记账、不打断执行流 — 永不 raise.
账本是纯数据结构: 不依赖 EventBus / IO, 状态迁移全在内存.

状态机: unverified → verified (首次 verify); falsify 是终态不回翻;
verify 在已 verified 的断言上重复调用会继续累计 pass_count — 这是
M3 验证阶梯"连续 N 次稳定通过"的原始计数输入 (本层只计数不判断).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from layers.contract.assertion import Assertion, AssertionStatus


class EdgeType(str, Enum):
    """四种溯源边 (设计稿 4.1.4)."""

    DERIVE = "derive"  # 这个值从哪一步/哪条断言流出来
    DEPENDS_ON = "depends_on"  # 这条断言假定哪条前置断言成立 (反向搜索主边)
    INVALIDATES = "invalidates"  # 这次观测证伪了哪条断言 (根因候选)
    TRIGGER = "trigger"  # 这条断言失败触发了哪个动作 (修复链审计)


class FalsificationRecord:
    """一次证伪的账面记录."""

    __slots__ = ("aid", "observed_by", "ts")

    def __init__(self, aid: str, observed_by: str, ts: datetime) -> None:
        self.aid = aid
        self.observed_by = observed_by
        self.ts = ts

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"FalsificationRecord(aid={self.aid!r}, "
            f"by={self.observed_by!r}, ts={self.ts.isoformat()})"
        )


class AssertionLedger:
    """断言账本. 节点 = 断言; 边 = 四种溯源关系.

    边方向约定 (统一): src --edge--> dst 表示"src 依赖/源自 dst".
    因此: 从症状回追根因 = 沿 DEPENDS_ON 边向 dst 走 (downstream);
    污染锥 (谁被我影响) = 反向 (upstream). T1.2 的 causal.py 用
    prerequisites()/dependents() 这两个无歧义别名, 不直接用上下游.
    """

    def __init__(self) -> None:
        self._assertions: dict[str, Assertion] = {}
        # _edges[t][src] = {dst, ...}; 有向
        self._edges: dict[EdgeType, dict[str, set[str]]] = {t: {} for t in EdgeType}
        self._falsifications: list[FalsificationRecord] = []
        self._first_falsification: dict[str, FalsificationRecord] = {}
        self._pass_counts: dict[str, int] = {}

    # ── 节点 ────────────────────────────────────────────────────────────

    def add(self, assertion: Assertion) -> None:
        """登记断言. 重复 aid 是编程错误, 直接炸 (与 falsify 的宽容相反)."""
        if assertion.aid in self._assertions:
            raise ValueError(f"duplicate assertion aid: {assertion.aid!r}")
        self._assertions[assertion.aid] = assertion

    def get(self, aid: str) -> Assertion:
        return self._assertions[aid]

    def has(self, aid: str) -> bool:
        return aid in self._assertions

    def list_assertions(self) -> list[Assertion]:
        return list(self._assertions.values())

    # ── 边 ──────────────────────────────────────────────────────────────

    def _add_edge(self, t: EdgeType, src: str, dst: str) -> None:
        self._edges[t].setdefault(src, set()).add(dst)

    def depends_on(self, aid: str, prerequisite_aid: str) -> None:
        """aid 假定 prerequisite_aid 成立 (反向搜索主边)."""
        self._add_edge(EdgeType.DEPENDS_ON, aid, prerequisite_aid)

    def derives_from(self, aid: str, source_aid: str) -> None:
        """aid 的值从 source_aid 流出来."""
        self._add_edge(EdgeType.DERIVE, aid, source_aid)

    def triggered(self, aid: str, action_id: str) -> None:
        """aid 失败触发了 action_id (动作不是断言, 节点允许任意 id)."""
        self._add_edge(EdgeType.TRIGGER, aid, action_id)

    def invalidates(self, observer_id: str, aid: str) -> None:
        """observer_id 的这次观测证伪了 aid (falsify 内部也会记)."""
        self._add_edge(EdgeType.INVALIDATES, observer_id, aid)

    def upstream(self, aid: str, edge: EdgeType = EdgeType.DEPENDS_ON) -> set[str]:
        """沿某类边反向: 谁指向 aid (= dependents, 污染锥方向)."""
        return {src for src, dsts in self._edges[edge].items() if aid in dsts}

    def downstream(self, aid: str, edge: EdgeType = EdgeType.DEPENDS_ON) -> set[str]:
        """沿某类边正向: aid 指向谁 (= prerequisites, 回追根因方向)."""
        return set(self._edges[edge].get(aid, ()))

    def prerequisites(self, aid: str) -> set[str]:
        """aid 依赖哪些断言 (回追根因的走法, T1.2 用)."""
        return self.downstream(aid, EdgeType.DEPENDS_ON)

    def dependents(self, aid: str) -> set[str]:
        """哪些断言依赖 aid (污染锥的走法, T1.2 用)."""
        return self.upstream(aid, EdgeType.DEPENDS_ON)

    # ── 状态迁移 (只记账, 不打断) ────────────────────────────────────────

    def falsify(
        self, aid: str, observed_by: str = "", ts: datetime | None = None
    ) -> FalsificationRecord | None:
        """证伪记账. 未知 aid → None (抛异常打断执行流是设计禁止项);
        已证伪 → 幂等返回该断言的首次证伪记录; 否则置状态 + 记 invalidates 边
        + 清零 pass_count (M3 的"连续通过"就此打断).
        """
        cur = self._assertions.get(aid)
        if cur is None:
            return None
        first = self._first_falsification.get(aid)
        if first is not None:
            return first
        rec = FalsificationRecord(
            aid=aid, observed_by=observed_by, ts=ts or datetime.now()
        )
        self._assertions[aid] = cur.model_copy(
            update={"status": AssertionStatus.FALSIFIED}
        )
        self._first_falsification[aid] = rec
        self._falsifications.append(rec)
        self._pass_counts[aid] = 0
        if observed_by:
            self._add_edge(EdgeType.INVALIDATES, observed_by, aid)
        return rec

    def verify(self, aid: str) -> bool:
        """验证通过记账. falsified 是终态, verify 不回翻 → False.
        未知 aid → False (不抛). 通过则置 verified 并累计 pass_count.
        """
        cur = self._assertions.get(aid)
        if cur is None or cur.status is AssertionStatus.FALSIFIED:
            return False
        if cur.status is not AssertionStatus.VERIFIED:
            self._assertions[aid] = cur.model_copy(
                update={"status": AssertionStatus.VERIFIED}
            )
        self._pass_counts[aid] = self._pass_counts.get(aid, 0) + 1
        return True

    # ── 查询 ────────────────────────────────────────────────────────────

    def status(self, aid: str) -> AssertionStatus | None:
        a = self._assertions.get(aid)
        return a.status if a is not None else None

    def falsification_log(self) -> list[FalsificationRecord]:
        return list(self._falsifications)

    def pass_count(self, aid: str) -> int:
        """累计通过次数 (falsify 清零). M3 阶梯的原始输入, 本层只计数不判断."""
        return self._pass_counts.get(aid, 0)
