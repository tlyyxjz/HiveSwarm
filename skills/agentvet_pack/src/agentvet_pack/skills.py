"""AgentVet L1-L4 skill 实现.

设计: 绕开 FastAPI 启动, 直接 import scanner.engine, 跑本地扫描.
每个 skill = 1 个 class, 都实现 core/skill.py 的 Skill ABC.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.skill import Skill, SkillHealth, SkillManifest

_log = logging.getLogger(__name__)


# 延迟 import, 避免 hive 启动就强依赖 agentvet
def _get_engine():
    """延迟 import agentvet scanner. 失败不抛, 留给 run 时报."""
    try:
        from scanner.engine import ScanEngine
        from scanner.findings import ScanReport
        return ScanEngine, ScanReport
    except ImportError as exc:
        raise RuntimeError(
            f"agentvet not installed: {exc}. "
            f"install with: pip install -e C:/Users/Lenovo/Desktop/agentvet"
        ) from exc


def _level_to_kwargs(level: int) -> dict:
    """level → engine kwargs. AgentVet 内部按 level 跑不同深度."""
    if level == 1:
        return {"use_l2": False, "use_l3": False, "use_l4": False}
    if level == 2:
        return {"use_l2": True, "use_l3": False, "use_l4": False}
    if level == 3:
        return {"use_l2": True, "use_l3": True, "use_l4": False}
    # L4
    return {"use_l2": True, "use_l3": True, "use_l4": True}


class _AgentVetBaseSkill(Skill):
    """L1-L4 的基类, 复用 scan 流程, 只 level 不同."""

    def __init__(self, level: int) -> None:
        super().__init__(SkillManifest(
            name=f"agentvet_l{level}",
            api_version="1.0",
            description=f"AgentVet L{level} scan",
            tags=("security", "scan", f"l{level}"),
        ))
        self._level = level

    def run(self, input_data: dict) -> dict:
        target = input_data.get("target", "")
        if not target:
            return {"ok": False, "error": "target is required", "level": self._level}
        if not Path(target).exists():
            return {"ok": False, "error": f"target not found: {target}", "level": self._level}

        try:
            ScanEngine, ScanReport = _get_engine()
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc), "level": self._level}

        try:
            engine = ScanEngine(**_level_to_kwargs(self._level))
            report = engine.scan(target)
            # 提取 score (可能 enum 或 str)
            raw_score = getattr(report, "score", None)
            if raw_score is not None and hasattr(raw_score, "value"):
                score = raw_score.value
            else:
                score = str(raw_score) if raw_score is not None else None
            # 提取 findings
            findings = getattr(report, "findings", []) or []
            return {
                "ok": True,
                "level": self._level,
                "target": target,
                "score": score,
                "findings_count": len(findings),
                "findings": [
                    {
                        "level": str(getattr(f, "severity", "?")),
                        "message": getattr(f, "message", str(f)),
                        "file": getattr(f, "file", ""),
                        "rule_id": getattr(f, "rule_id", ""),
                    }
                    for f in findings[:20]
                ],
            }
        except Exception as exc:  # noqa: BLE001
            _log.exception("agentvet scan failed")
            return {"ok": False, "error": f"scan failed: {exc}", "level": self._level}

    async def health_check(self) -> SkillHealth:
        try:
            _get_engine()
            return SkillHealth(name=self.manifest.name, success_count=1)
        except Exception as exc:  # noqa: BLE001
            h = SkillHealth(name=self.manifest.name, last_error=str(exc))
            h.failure_count += 1
            return h


# 具体 4 个 skill class
class ScanL1Skill(_AgentVetBaseSkill):
    def __init__(self) -> None:
        super().__init__(level=1)


class ScanL2Skill(_AgentVetBaseSkill):
    def __init__(self) -> None:
        super().__init__(level=2)


class ScanL3Skill(_AgentVetBaseSkill):
    def __init__(self) -> None:
        super().__init__(level=3)


class ScanL4Skill(_AgentVetBaseSkill):
    def __init__(self) -> None:
        super().__init__(level=4)


# 注册入口(给 Pool 用)
def register_all(pool) -> int:
    """把 4 个 skill 全部注册到 pool. 返回注册数."""
    n = 0
    for cls in (ScanL1Skill, ScanL2Skill, ScanL3Skill, ScanL4Skill):
        try:
            pool.register(cls())
            n += 1
        except Exception as exc:  # noqa: BLE001
            _log.warning("register %s failed: %s", cls.__name__, exc)
    return n
