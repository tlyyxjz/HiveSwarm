"""Agent — 临时智能体 ABC.

职责:工厂 (factory) 组装 + 销毁. 借来的 skills 注入到 self.skills, 任务
跑完调 destroy() 释放. **不持久化,任务结束就丢**.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Agent(ABC):
    """临时 Agent. 工厂建出来,任务结束就 destroy."""

    agent_id: str
    skills: list[str]  # 借来的技能名,只读

    @abstractmethod
    async def run(self, task: dict[str, Any]) -> dict[str, Any]:
        """执行任务. 输入输出都是 dict(JSON-like)."""

    @abstractmethod
    def destroy(self) -> None:
        """释放技能 + 清理资源. 调完不能再 run."""
