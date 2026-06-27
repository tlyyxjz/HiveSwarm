"""HiveSwarm skill pack: AgentVet scanner.

提供 4 个 skill:
  - agentvet_l1: 浅扫描, 检查 prompt injection 关键词
  - agentvet_l2: 中度扫描, 加 L2 规则
  - agentvet_l3: 深度扫描, 审计工具调用链
  - agentvet_l4: 攻击链分析

便捷入口:
  - AgentvetSkill: 单入口包装, CLI 优先, CLI 不可用则 stub 回退

用法:
    from agentvet_pack import AgentvetSkill
    skill = AgentvetSkill()
    result = skill.run({"target": "/path/to/code"})
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Any

from core.skill import Skill, SkillManifest
from .skills import (
    ScanL1Skill,
    ScanL2Skill,
    ScanL3Skill,
    ScanL4Skill,
    register_all,
)


class AgentvetSkill(Skill):
    """单入口 AgentVet 技能——优先用 agentvet CLI 扫描, CLI 不可用则返回 stub 结果.

    输入: {"target": "/path", "level": 1}  — level 可选, 默认 L1
    输出: {"ok": True, "target": ..., "level": ..., "stdout": ...}
    """

    def __init__(self) -> None:
        super().__init__(SkillManifest(
            name="agentvet",
            api_version="1.0",
            description="AgentVet AI 安全扫描（CLI 优先, 不可用则 stub 回退）",
            tags=("security", "scan", "agentvet"),
        ))

    def run(self, input_data: dict) -> dict:
        target = input_data.get("target", ".")
        level = int(input_data.get("level", 1))
        cli_path = shutil.which("agentvet")
        if cli_path:
            return self._run_cli(str(cli_path), str(target), level)
        return self._run_stub(str(target), level)

    def _run_cli(self, cli_path: str, target: str, level: int) -> dict:
        try:
            cp = subprocess.run(
                [cli_path, "scan", "--level", f"L{level}", target],
                capture_output=True, text=True, timeout=120,
            )
            return {
                "ok": cp.returncode == 0,
                "target": target,
                "level": level,
                "stdout": cp.stdout[:2000],
                "stderr": cp.stderr[:1000],
                "returncode": cp.returncode,
            }
        except Exception as exc:
            return {"ok": False, "error": f"CLI 执行失败: {exc}", "target": target, "level": level}

    def _run_stub(self, target: str, level: int) -> dict:
        return {
            "ok": True,
            "target": target,
            "level": level,
            "stub": True,
            "message": f"agentvet CLI 未找到 — stub L{level} 扫描完成",
        }


__version__ = "0.1.0"
__all__ = [
    "AgentvetSkill",
    "ScanL1Skill", "ScanL2Skill", "ScanL3Skill", "ScanL4Skill",
    "register_all",
]
