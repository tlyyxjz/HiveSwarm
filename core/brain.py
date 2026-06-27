"""Brain — 大脑 ABC.

职责:接收用户任务,拆成 Plan(子任务 DAG),决定每个子任务需要哪些
技能. Work 层拿 Plan 去借/装/跑.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SubTask:
    """子任务. 含需要的技能和验收标准."""

    sub_id: str
    intent: str
    required_skills: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()  # 前置子任务 sub_id
    acceptance: str = ""  # 通过/失败的标准,Inspect 拿这个验


@dataclass
class Plan:
    """一个任务的完整拆解."""

    task_id: str
    original_request: str
    subtasks: list[SubTask] = field(default_factory=list)
    rationale: str = ""  # 决策依据(给 Explainability 用)


class Brain(ABC):
    """大脑. 不同实现:LLM-Brain(默认)/ Rule-Brain(离线)/ Mock-Brain(测试)."""

    @abstractmethod
    async def plan(self, request: str, context: dict | None = None) -> Plan:
        """用户一句话 → Plan(DAG)."""

    @abstractmethod
    async def decide(
        self, plan: Plan, observations: list[dict]
    ) -> tuple[str, str]:
        """修补失败时,决定下一步(switch_skill/re_assemble/halt).

        Returns: (action, reason). action: "switch"|"reassemble"|"halt".
        """
