"""ppt_pack 单测 - 4 步 PPT 流水线."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills" / "ppt_pack" / "src"))

from ppt_pack import (
    DataCollectSkill,
    ExportSkill,
    LayoutSkill,
    OutlineSkill,
    register_all,
)
from layers.work.pool import SkillPool


# ── 单 skill 行为 ────────────────────────────────────────────

class TestDataCollect:
    def test_basic_collect(self):
        s = DataCollectSkill()
        out = s.run({"topic": "Q3 复盘"})
        assert out["ok"] is True
        assert out["topic"] == "Q3 复盘"
        assert "sections" in out["data"]
        assert "stats" in out["data"]

    def test_missing_topic_uses_default(self):
        s = DataCollectSkill()
        out = s.run({})
        assert out["ok"] is True
        assert out["topic"]  # 有默认


class TestOutline:
    def test_basic_outline(self):
        s = OutlineSkill()
        out = s.run({"data": {"title": "AI 趋势", "sections": ["A", "B", "C"]}})
        assert out["ok"] is True
        assert len(out["outline"]["slides"]) == 3
        assert out["outline"]["title"] == "AI 趋势"

    def test_outline_with_topic_only(self):
        s = OutlineSkill()
        out = s.run({"topic": "x"})
        assert out["ok"] is True
        # 默认 sections = ["概述", "详情", "结论"]
        assert len(out["outline"]["slides"]) == 3


class TestLayout:
    def test_basic_layout(self):
        s = LayoutSkill()
        out = s.run({"outline": {"title": "T", "slides": [{"title": "S1", "bullet_points": ["a", "b"]}]}})
        assert out["ok"] is True
        assert "# T" in out["markdown"]
        assert "## S1" in out["markdown"]


class TestExport:
    def test_export_pptx(self):
        s = ExportSkill()
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            out_path = f.name
        try:
            md = "# Title\n\n## Slide1\n- point a\n- point b"
            out = s.run({"markdown": md, "output": out_path})
            assert out["ok"] is True
            assert out["file"] == out_path
            assert out["size_kb"] > 0
            assert os.path.exists(out_path)
            # 真 pptx 文件
            with open(out_path, "rb") as f:
                header = f.read(4)
            assert header == b"PK\x03\x04"  # ZIP/pptx 魔数
        finally:
            if os.path.exists(out_path):
                os.remove(out_path)

    def test_export_missing_input_fails(self):
        s = ExportSkill()
        out = s.run({})
        assert out["ok"] is False
        assert "error" in out


# ── register_all / Pool 集成 ─────────────────────────────────

class TestPoolIntegration:
    def test_register_all(self):
        pool = SkillPool()
        n = register_all(pool)
        assert n == 4
        assert set(pool.list_available()) == {"data_collect", "outline", "layout", "export"}

    def test_checkout_return_back(self):
        pool = SkillPool()
        register_all(pool)
        bundle = pool.checkout(["data_collect", "outline"])
        health = pool.health_report()
        assert health["data_collect"]["refcount"] == 1
        assert health["outline"]["refcount"] == 1
        pool.return_back(bundle)
        health = pool.health_report()
        assert health["data_collect"]["refcount"] == 0
        assert health["outline"]["refcount"] == 0


# ── 完整 4 步流水线 ──────────────────────────────────────────

class TestFullPipeline:
    def test_4_step_chain(self):
        c = DataCollectSkill()
        o = OutlineSkill()
        l = LayoutSkill()
        e = ExportSkill()

        r1 = c.run({"topic": "测试主题"})
        assert r1["ok"]

        r2 = o.run({"data": r1["data"]})
        assert r2["ok"]
        assert len(r2["outline"]["slides"]) >= 3

        r3 = l.run({"outline": r2["outline"]})
        assert r3["ok"]
        assert len(r3["markdown"]) > 50

        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            out = f.name
        try:
            r4 = e.run({"markdown": r3["markdown"], "output": out})
            assert r4["ok"]
            assert os.path.getsize(out) > 1000  # 至少 1KB
        finally:
            os.remove(out)