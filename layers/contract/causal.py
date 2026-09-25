"""causal — 反向可达搜索 + 污染锥 + 只重跑集合 (榫卯 M2 前半, T1.2).

与 LongRCA 的范式差异 (设计稿 4.2.3): 不在文本轨迹里"猜"根因步,
而是沿类型化依赖边做确定性图搜索 — 从失败断言出发, 找"最早被证伪"
的那一条 (离症状图距离最远的被证伪节点), 根因步 = 该断言的 producer.

三个纯函数, 只依赖 AssertionLedger, 不发事件不 IO — 正确性靠测试证明.
"""
from __future__ import annotations

from dataclasses import dataclass

from layers.contract.assertion import AssertionStatus
from layers.contract.ledger import AssertionLedger


@dataclass(frozen=True)
class RootCause:
    """反向搜索的结论. path[0] = 症状, path[-1] = 根因."""

    aid: str
    distance: int  # 距症状的图距离 (0 = 症状自身即根因)
    path: tuple[str, ...]


def find_root_cause(ledger: AssertionLedger, symptom_aid: str) -> RootCause | None:
    """从症状断言出发, 沿 DEPENDS_ON 边反向搜索, 返回"最早被证伪"的那条.

    最早 = 离症状图距离最远的被证伪节点 (设计稿 4.2.3: 报错位置 ≠ 根因).
    症状自身未被证伪 / aid 不存在 / 可达集里没有任何被证伪节点 → None.
    环路安全: visited 集合保证终止.
    平局 (同距离多条被证伪): 取 aid 字典序最小者, 保证确定性.
    """
    if not ledger.has(symptom_aid):
        return None
    visited: set[str] = set()
    frontier: list[tuple[str, tuple[str, ...]]] = [(symptom_aid, (symptom_aid,))]
    best: tuple[int, str, tuple[str, ...]] | None = None  # (-distance, aid, path) 取 max
    while frontier:
        aid, path = frontier.pop()
        if aid in visited:
            continue
        visited.add(aid)
        if ledger.status(aid) is AssertionStatus.FALSIFIED:
            dist = len(path) - 1
            # 距离最大者优先; 同距离取 aid 字典序最小 → 比较 (-dist, aid) 取最小
            key = (-dist, aid)
            if best is None or key < (-best[0], best[1]):
                best = (dist, aid, path)
        for prereq in sorted(ledger.prerequisites(aid)):
            if prereq not in visited:
                frontier.append((prereq, path + (prereq,)))
    if best is None:
        return None
    dist, aid, path = best
    return RootCause(aid=aid, distance=dist, path=path)


def contamination_cone(ledger: AssertionLedger, root_aid: str) -> frozenset[str]:
    """污染锥: 根因断言的全部下游 (transitive dependents) + 根因自身.

    锥内产出标记"不可信" — 注意锥不含根因的上游 (它们的产出仍然可信).
    环路安全.
    """
    if not ledger.has(root_aid):
        return frozenset()
    cone: set[str] = set()
    stack = [root_aid]
    while stack:
        aid = stack.pop()
        if aid in cone:
            continue
        cone.add(aid)
        stack.extend(ledger.dependents(aid))
    return frozenset(cone)


def rerun_set(ledger: AssertionLedger, root_aid: str) -> frozenset[str]:
    """只重跑集合: 从根因步起的依赖子图 = 锥内所有断言的 producer 步骤.

    producer 为空的断言 (无步骤归属) 跳过. EvidenceBound 已做过选择性重跑,
    这是工程收益指标, 不是创新点 (设计稿 4.2.5 的诚实定位).
    """
    cone = contamination_cone(ledger, root_aid)
    steps = set()
    for aid in cone:
        producer = ledger.get(aid).producer
        if producer:
            steps.add(producer)
    return frozenset(steps)
