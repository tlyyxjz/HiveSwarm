"""StrategyTable — 失败模式 → 修补策略.

历史层: StrategyTable 关键词匹配 (旧路径, 保留兼容, 其测试原样有效).
榫卯 M2 (T1.3): TypedDispatch — 被证伪断言的【类型】→ 结构化修复动作,
从"猜错误文本"变成"查类型表", 类型完备 (每个 (kind, 谓词类) 组合唯一动作).
见 docs/任务单_T13_类型驱动修复.md.
"""
from __future__ import annotations

from dataclasses import dataclass

from layers.contract.assertion import Assertion, AssertionKind
from layers.contract.causal import find_root_cause
from layers.contract.ledger import AssertionLedger


@dataclass(frozen=True)
class RepairAction:
    """一条修补策略."""

    name: str  # 旧: switch_skill|re_assemble|halt; 新增: swap_adapter|re_observe|halt_escalate
    reason: str  # 解释为什么选这个


class StrategyTable:
    """失败模式 → 策略, 字典 + 兜底. (旧关键词路径, 保留兼容)"""

    DEFAULT_TABLE: dict[str, str] = {
        # 关键词 → 动作
        "length": "switch_skill",     # 长度问题,换技能(换个能产长的)
        "pattern": "re_assemble",     # 格式不对,重组 SubTask
        "score": "switch_skill",      # LLM judge 分数低,换技能
        "missing": "re_assemble",     # 缺字段,重组
        "timeout": "halt",            # 超时,人审
        "permission": "halt",         # 权限,人审
    }

    DEFAULT_FALLBACK = "re_assemble"

    def __init__(self, table: dict[str, str] | None = None, fallback: str = ""):
        # 合并, 用户传的部分覆盖默认
        self._table: dict[str, str] = dict(self.DEFAULT_TABLE)
        if table:
            self._table.update(table)
        self._fallback = fallback or self.DEFAULT_FALLBACK

    def lookup(self, error: str) -> str:
        """根据错误文本查动作. 找不到走 fallback."""
        error_lower = error.lower()
        for keyword, action in self._table.items():
            if keyword in error_lower:
                return action
        return self._fallback

    def explain(self, error: str) -> RepairAction:
        action = self.lookup(error)
        return RepairAction(name=action, reason=f"matched keyword in: {error[:80]}")


# 6 原语 → 证伪类型. 表即"证伪类型学"的一半; 不在表里的原语进不来
# (Assertion 模型层已用白名单锁死).
PREDICATE_CLASS: dict[str, str] = {
    "has_keys": "shape",  # 形状错: 结构/字段不对
    "in_range": "value",  # 值错: 格式合法但取值不对
    "regex_match": "value",
    "min_length": "threshold",  # 未达标: 长度/数量不够
    "max_length": "threshold",
    "not_empty": "existence",  # 存在错: 该有的东西没有
}

STRUCTURAL_ACTIONS = ("swap_adapter", "re_observe", "swap_skill", "re_assemble", "halt_escalate")

# 完整 dispatch 表 (kind, 证伪类型) → 动作. 类型完备: 无 fallback 格子.
# 设计稿 4.2.2 给了 6 行; pre+threshold 与 post+value/existence 是本实现
# 为类型完备性补全的格子 (理由见任务单).
DISPATCH_TABLE: dict[tuple[str, str], str] = {
    # 不变量破 = 账本/预算被破坏, 不可自动修复 → 停机上报
    ("invariant", "shape"): "halt_escalate",
    ("invariant", "value"): "halt_escalate",
    ("invariant", "threshold"): "halt_escalate",
    ("invariant", "existence"): "halt_escalate",
    # pre: 输入侧. 形状是翻译问题 → 换适配器; 值/存在是世界变了 → 重新观测
    ("pre", "shape"): "swap_adapter",
    ("pre", "threshold"): "swap_adapter",
    ("pre", "value"): "re_observe",
    ("pre", "existence"): "re_observe",
    # post: 输出侧. 未达标是技能没干成 → 换技能; 形状/存在是意图落空 → 重组;
    # 值错先重新取证 (与 pre 值类同源, 不轻易动装配)
    ("post", "threshold"): "swap_skill",
    ("post", "shape"): "re_assemble",
    ("post", "existence"): "re_assemble",
    ("post", "value"): "re_observe",
}


class TypedDispatch:
    """被证伪断言的类型 → 结构化修复动作 (M2 核心, 替代关键词猜测)."""

    def dispatch(self, assertion: Assertion) -> RepairAction:
        """查表. 断言谓词白名单 + 表完备性共同保证必然有唯一动作."""
        kind = (
            assertion.kind.value
            if isinstance(assertion.kind, AssertionKind)
            else str(assertion.kind)
        )
        pclass = PREDICATE_CLASS.get(assertion.validator_name)
        if pclass is None:
            # 模型层白名单已挡住, 这里是纵深防御
            raise ValueError(f"unclassified predicate: {assertion.validator_name!r}")
        action = DISPATCH_TABLE[(kind, pclass)]
        return RepairAction(
            name=action,
            reason=(
                f"falsified {kind} assertion {assertion.aid!r} "
                f"({pclass} class, predicate={assertion.predicate})"
            ),
        )

    def from_falsified(
        self, ledger: AssertionLedger, symptom_aid: str
    ) -> tuple[RepairAction, str] | None:
        """端到端: 症状断言 → 反向搜索根因 (T1.2) → 对根因 dispatch.
        返回 (动作, 根因 aid); 症状无效或无可证伪根因 → None.
        """
        rc = find_root_cause(ledger, symptom_aid)
        if rc is None:
            return None
        root = ledger.get(rc.aid)
        return self.dispatch(root), rc.aid
