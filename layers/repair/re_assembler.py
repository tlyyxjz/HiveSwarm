"""ReAssembler — 拿到 FixPlan 重组 SubTask.

支持:
  - 改 intent (换思路)
  - 加/换 skills
  - 拆成多个 SubTask (复杂场景, 留接口)
"""
from __future__ import annotations

from dataclasses import replace

from core.brain import SubTask
from layers.repair.fixer import FixPlan


class ReAssembler:
    """重组 SubTask. 单职责, 不调用 LLM, 不调 Pool."""

    def reassemble(self, original: SubTask, plan: FixPlan) -> SubTask:
        """根据 FixPlan 改 SubTask. 不支持拆, 只改."""
        if plan.action == "switch_skill" and plan.new_skills:
            return replace(original, required_skills=plan.new_skills)
        if plan.action == "re_assemble" and plan.new_intent:
            return replace(original, intent=plan.new_intent)
        # halt 或其他 → 原样返回, 调上层处理
        return original
