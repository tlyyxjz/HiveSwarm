"""typed_fixer — TypedDispatch 结果 → FixPlan 桥 (榫卯 M2, T1.3).

复用 fixer.FixPlan 结构与 re_assembler 的重装配能力, 不另起炉灶
(任务包 T1.3 要求 1). 独立模块避免 strategy_table ↔ fixer 循环 import.
"""
from __future__ import annotations

from layers.contract.assertion import Assertion
from layers.contract.ledger import AssertionLedger
from layers.repair.fixer import FixPlan
from layers.repair.strategy_table import RepairAction, TypedDispatch


def to_fix_plan(
    action: RepairAction,
    target_subtask: str,
    *,
    new_skills: tuple[str, ...] = (),
    new_intent: str | None = None,
) -> FixPlan:
    """把 typed dispatch 的动作装进既有 FixPlan 结构.

    new_skills 语义沿用 Fixer 约定: swap_skill 时由上层从能力池候选里
    选定后传入, dispatch 层不凭空造能力 (任务包 T1.3 要求 2).
    """
    return FixPlan(
        action=action.name,
        target_subtask=target_subtask,
        reason=action.reason,
        new_skills=new_skills or None,
        new_intent=new_intent,
    )


def plan_for_symptom(
    ledger: AssertionLedger,
    symptom_aid: str,
    dispatch: TypedDispatch | None = None,
    *,
    new_skills: tuple[str, ...] = (),
) -> FixPlan | None:
    """端到端便捷入口: 症状 → 根因 → 动作 → FixPlan. 无根因 → None."""
    d = dispatch or TypedDispatch()
    result = d.from_falsified(ledger, symptom_aid)
    if result is None:
        return None
    action, root_aid = result
    root: Assertion = ledger.get(root_aid)
    return to_fix_plan(
        action,
        target_subtask=root.producer or root_aid,
        new_skills=new_skills if action.name == "swap_skill" else (),
    )
