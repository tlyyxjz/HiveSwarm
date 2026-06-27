"""StrategyTable — 失败模式 → 修补策略, 配置驱动.

key 是 inspect 报错的关键词, value 是修补动作.
通过 config/repair.toml 加载 (Phase 1 暂时内置, Day 5+ 走文件).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RepairAction:
    """一条修补策略."""

    name: str  # "switch_skill" | "re_assemble" | "halt"
    reason: str  # 解释为什么选这个


class StrategyTable:
    """失败模式 → 策略, 字典 + 兜底."""

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
