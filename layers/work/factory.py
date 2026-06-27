"""AgentFactory — 临时 Agent 动态装配 + 销毁.

核心流程:
  subtask: required_skills = ["scan_l1", "fetch"]
    ↓
  pool.checkout(["scan_l1", "fetch"])  →  Bundle
    ↓
  TempAgent(skills=bundle.skills)  →  instance
    ↓
  instance.run(task_dict)  →  result
    ↓
  instance.destroy()  →  release
  pool.return_back(bundle)  →  归还

TempAgent 是一次性的:destroy 后再 run 报错.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from core.agent import Agent
from core.brain import SubTask
from core.skill import Skill
from core.skill_bundle import Borrowed
from layers.work.pool import SkillPool

_log = logging.getLogger(__name__)


class AgentAlreadyDestroyedError(RuntimeError):
    """agent 销毁后还调 run."""


class TempAgent(Agent):
    """临时 Agent. 工厂造出来,任务结束即销毁.

    skills 存名(只读),执行时按名调 skill.run.
    """

    def __init__(self, skills: list[Skill], agent_id: str | None = None) -> None:
        self.agent_id = agent_id or f"agent-{uuid.uuid4().hex[:8]}"
        self.skills: list[str] = [s.manifest.name for s in skills]
        self._skill_objs: dict[str, Skill] = {s.manifest.name: s for s in skills}
        self._destroyed: bool = False

    async def run(self, task: dict[str, Any]) -> dict[str, Any]:
        if self._destroyed:
            raise AgentAlreadyDestroyedError(f"agent {self.agent_id} already destroyed")

        intent = task.get("intent", "")
        skill_name = task.get("skill")
        if not skill_name:
            # 默认用第一个技能
            if not self._skill_objs:
                return {"agent": self.agent_id, "ok": False, "error": "no skills"}
            skill_name = next(iter(self._skill_objs))

        skill = self._skill_objs.get(skill_name)
        if skill is None:
            return {
                "agent": self.agent_id,
                "ok": False,
                "error": f"skill {skill_name!r} not in this agent",
            }

        try:
            result = skill.run(task.get("input", {}))
            return {
                "agent": self.agent_id,
                "skill": skill_name,
                "ok": True,
                "result": result,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "agent": self.agent_id,
                "skill": skill_name,
                "ok": False,
                "error": str(exc),
            }

    def destroy(self) -> None:
        """标记销毁. 实际技能释放由 Bundle / Pool 负责."""
        if self._destroyed:
            return
        self._destroyed = True
        self._skill_objs.clear()
        _log.debug("agent %s destroyed", self.agent_id)


class AgentFactory:
    """造临时 Agent,配 Borrowed 自动归还."""

    def __init__(self, pool: SkillPool) -> None:
        self._pool = pool

    def assemble(
        self,
        subtask: SubTask,
        agent_id: str | None = None,
    ) -> tuple[TempAgent, Borrowed]:
        """装配 + 返回 (agent, borrowed_ctx). 用户用 with 块调 agent.run.

        返回元组是刻意的:让调用方必须显式 with Borrowed(...) 借出 + 归还.
        """
        bundle = self._pool.checkout(list(subtask.required_skills))
        agent = TempAgent(bundle.skills, agent_id=agent_id)
        borrowed = Borrowed(bundle, self._pool)
        return agent, borrowed

    def assemble_and_run(
        self,
        subtask: SubTask,
        task_input: dict[str, Any],
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """一键: 装配 + 跑 + 销毁 + 归还. 出错也保证清理."""
        import asyncio

        agent, borrowed_ctx = self.assemble(subtask, agent_id=agent_id)
        with borrowed_ctx:
            try:
                result = asyncio.run(agent.run({"input": task_input, "intent": subtask.intent}))
                return result
            finally:
                agent.destroy()
