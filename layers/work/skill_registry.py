"""Skill registry utilities - central skill registration logic.

Extracted from src/main.py to share between CLI and gateway implementations.
"""
from __future__ import annotations

import sys
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from core.skill import Skill, SkillManifest
from layers.work.pool import SkillPool

if TYPE_CHECKING:
    from core.brain import Plan

_log = logging.getLogger(__name__)


# 计划关键词 → 技能名映射
_PLAN_TO_SKILLS = {
    "data_collect", "outline", "layout", "export",
    "agentvet_l1", "agentvet_l2", "agentvet_l3", "agentvet_l4",
    "web_search",
}


class _EchoSkill(Skill):
    """内置 mock skill, 让 demo 跑得起来."""

    def __init__(self, name: str) -> None:
        super().__init__(SkillManifest(name=name, api_version="1.0"))

    def run(self, input_data: dict) -> dict:
        return {"by": self.manifest.name, "echo": input_data, "ok": True}


def _try_register_real_skill(pool: SkillPool, name: str) -> bool:
    """尝试从真技能包注册. 成功返回 True.

    当前支持的包:
      - agentvet_l1/l2/l3/l4 → agentvet_pack (示例: AI 安全扫描)
      - http_fetch/url_extract/http_post → crawler_pack (通用 HTTP)
    """
    try:
        from pathlib import Path
        if name.startswith("agentvet_"):
            _pack_src = Path(__file__).parent.parent.parent / "skills" / "agentvet_pack" / "src"
            cls_map = {
                "agentvet_l1": "ScanL1Skill", "agentvet_l2": "ScanL2Skill",
                "agentvet_l3": "ScanL3Skill", "agentvet_l4": "ScanL4Skill",
            }
            module_name = "agentvet_pack.skills"
        elif name.startswith("http_") or name == "url_extract":
            _pack_src = Path(__file__).parent.parent.parent / "skills" / "crawler_pack" / "src"
            cls_map = {
                "http_fetch": "HttpFetchSkill",
                "url_extract": "UrlExtractSkill",
                "http_post": "HttpPostSkill",
            }
            module_name = "crawler_pack.skills"
        elif name in ("data_collect", "outline", "layout", "export"):
            _pack_src = Path(__file__).parent.parent.parent / "skills" / "ppt_pack" / "src"
            cls_map = {
                "data_collect": "DataCollectSkill",
                "outline": "OutlineSkill",
                "layout": "LayoutSkill",
                "export": "ExportSkill",
            }
            module_name = "ppt_pack.skills"
        elif name == "web_search":
            _pack_src = Path(__file__).parent.parent.parent / "skills" / "web_search_pack" / "src"
            cls_map = {"web_search": "WebSearchSkill"}
            module_name = "web_search_pack"
        else:
            return False

        if str(_pack_src) not in sys.path:
            sys.path.insert(0, str(_pack_src))

        import importlib
        mod = importlib.import_module(module_name)
        cls_name = cls_map.get(name)
        if cls_name is None or not hasattr(mod, cls_name):
            return False
        cls = getattr(mod, cls_name)
        pool.register(cls())
        return True
    except Exception as exc:  # noqa: BLE001
        _log.warning("real skill %s load failed: %s", name, exc)
        return False


def register_needed_skills(pool: SkillPool, plan: "Plan") -> None:
    """根据 plan 里的 required_skills 注册实现. 优先真技能包, 失败回 mock.

    Args:
        pool: SkillPool to register skills into
        plan: Plan containing subtasks with required_skills
    """
    seen: set[str] = set()
    for sub in plan.subtasks:
        for s in sub.required_skills:
            if s in seen:
                continue
            # 先试真技能包, 失败回 mock
            if not _try_register_real_skill(pool, s):
                pool.register(_EchoSkill(s))
            seen.add(s)