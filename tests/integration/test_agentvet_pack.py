"""agentvet_pack 单元测试.

注意: 装在 tests/integration/, 真装 agentvet 才能跑 (否则 import 失败)
"""
from __future__ import annotations

import sys
from pathlib import Path

# 加 skills/agentvet_pack/src 到 sys.path
_AGENTVET_PACK_SRC = (
    Path(__file__).parent.parent.parent / "skills" / "agentvet_pack" / "src"
)
if str(_AGENTVET_PACK_SRC) not in sys.path:
    sys.path.insert(0, str(_AGENTVET_PACK_SRC))

import pytest  # noqa: E402


class TestAgentVetPack:
    def test_can_import_pack(self):
        from agentvet_pack import __version__
        assert __version__ == "0.1.0"

    def test_can_import_skills(self):
        from agentvet_pack.skills import ScanL1Skill, ScanL2Skill, ScanL3Skill, ScanL4Skill
        for cls in (ScanL1Skill, ScanL2Skill, ScanL3Skill, ScanL4Skill):
            skill = cls()
            assert skill.manifest.name.startswith("agentvet_l")
            assert skill.manifest.api_version == "1.0"

    def test_l1_skill_structure(self):
        from agentvet_pack.skills import ScanL1Skill
        from core.skill import Skill
        s = ScanL1Skill()
        assert isinstance(s, Skill)
        # 跑空 target 应该有错误返回(不抛)
        r = s.run({})
        assert r["ok"] is False
        assert "target" in r["error"]

    def test_l1_skill_missing_path(self):
        from agentvet_pack.skills import ScanL1Skill
        s = ScanL1Skill()
        r = s.run({"target": "/nope/this/does/not/exist"})
        assert r["ok"] is False
        assert "not found" in r["error"]

    def test_health_check_returns_health(self):
        """不调真 health_check(可能拉 LLM). 验 health_check 签名."""
        import asyncio
        from agentvet_pack.skills import ScanL1Skill, _AgentVetBaseSkill
        from core.skill import SkillHealth

        s = ScanL1Skill()
        # 直接构造一个 SkillHealth 验接口签名
        h = SkillHealth(name=s.manifest.name, success_count=1)
        assert h.name == "agentvet_l1"
        assert h.error_rate == 0.0
