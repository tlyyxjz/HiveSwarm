"""Fixer — 接收 inspect 失败, 产出 repair plan.

不直接动脑子改 SubTask, 只负责"问 strategy 表 → 给 plan".
真改由 re_assembler 做.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.brain import SubTask
from layers.inspect.checker import CheckReport
from layers.repair.strategy_table import RepairAction, StrategyTable


@dataclass
class FixPlan:
    """一个修补方案."""

    action: str  # "switch_skill" | "re_assemble" | "halt"
    target_subtask: str
    reason: str
    new_skills: tuple[str, ...] | None = None  # switch 时填
    new_intent: str | None = None  # re_assemble 时填


class Fixer:
    """看检查报告 → 出修补方案."""

    def __init__(self, table: StrategyTable | None = None) -> None:
        self._table = table or StrategyTable()

    def propose(
        self, subtask: SubTask, report: CheckReport
    ) -> FixPlan:
        """根据 inspect 报告给方案. 默认是 re_assemble."""
        # 聚合所有错误
        err_text = "; ".join(report.errors) if not report.ok else "ok"
        action_obj: RepairAction = self._table.explain(err_text)

        if action_obj.name == "switch_skill":
            return FixPlan(
                action="switch_skill",
                target_subtask=subtask.sub_id,
                reason=action_obj.reason,
                new_skills=(),  # 留给 Brain 决定换啥
            )
        if action_obj.name == "halt":
            return FixPlan(
                action="halt",
                target_subtask=subtask.sub_id,
                reason=action_obj.reason,
            )
        # default: re_assemble
        return FixPlan(
            action="re_assemble",
            target_subtask=subtask.sub_id,
            reason=action_obj.reason,
            new_intent=subtask.intent,  # 暂时不变,真重组由 re_assembler
        )
