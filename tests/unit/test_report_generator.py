"""ReportGenerator 单测 — 报告生成 + Markdown + PDF."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from core.events import Event, EventType
from layers.report.generator import ReportGenerator
from stub.bus_local import LocalEventBus


@pytest.fixture
def env(tmp_path: Path):
    """bus + reports dir."""
    bus = LocalEventBus()
    reports_dir = tmp_path / "reports"
    gen = ReportGenerator(bus=bus, memory=None, reports_dir=str(reports_dir))
    return bus, gen, reports_dir


def _sample_result(task_id: str = "t-100") -> dict:
    return {
        "task_id": task_id,
        "request": "帮我做一个 PPT",
        "rationale": "拆 4 步",
        "subtasks": ["s1", "s2", "s3", "s4"],
        "results": [
            {"sub_id": "s1", "ok": True, "error": None, "result": {"echo": "data"}},
            {"sub_id": "s2", "ok": True, "error": None, "result": {"outline": "5 章"}},
            {"sub_id": "s3", "ok": False, "error": "timeout", "result": None},
            {"sub_id": "s4", "ok": True, "error": None, "result": {"path": "/tmp/out.pptx"}},
        ],
        "all_ok": False,
        "success_count": 3,
        "fail_count": 1,
    }


def _feed_events(bus: LocalEventBus, task_id: str = "t-100") -> None:
    """喂一些事件让 report 有数据."""
    import time
    bus.publish(Event(type=EventType.TASK_STARTED, payload={"task_id": task_id, "rationale": "拆 4 步"}))
    time.sleep(0.01)
    bus.publish(Event(type=EventType.TASK_COMPLETED, payload={"task_id": task_id}))
    bus.publish(Event(type=EventType.TASK_FAILED, payload={"task_id": task_id, "subtask_id": "s3", "error": "timeout"}))
    bus.publish(Event(type=EventType.REPAIR_TRIGGERED, payload={"task_id": task_id, "action": "switch_skill"}))


# ── 基础生成 ───────────────────────────────────────────────

class TestGenerate:
    def test_returns_report_object(self, env) -> None:
        bus, gen, _ = env
        _feed_events(bus)
        r = gen.generate("t-100", "帮我做一个 PPT", _sample_result())
        assert r.task_id == "t-100"
        assert r.md_path is not None
        assert r.content_md != ""

    def test_writes_markdown_file(self, env) -> None:
        bus, gen, reports_dir = env
        _feed_events(bus)
        r = gen.generate("t-100", "帮我做一个 PPT", _sample_result())
        assert r.md_path.exists()
        assert r.md_path.suffix == ".md"
        assert r.md_path.parent == reports_dir

    def test_writes_pdf_if_reportlab_available(self, env) -> None:
        bus, gen, _ = env
        _feed_events(bus)
        r = gen.generate("t-100", "帮我做一个 PPT", _sample_result())
        # reportlab 已装, 应有 PDF
        assert r.pdf_path is not None
        assert r.pdf_path.exists()

    def test_handles_no_events(self, env) -> None:
        """bus 空 / 没事件 → 报告仍生成 (有 placeholder)."""
        _, gen, _ = env
        r = gen.generate("t-200", "空任务", _sample_result("t-200"))
        assert r.md_path is not None
        assert r.md_path.exists()


# ── Markdown 内容 ───────────────────────────────────────────

class TestMarkdownContent:
    def test_contains_basic_info(self, env) -> None:
        bus, gen, _ = env
        _feed_events(bus)
        r = gen.generate("t-100", "帮我做一个 PPT", _sample_result())
        assert "t-100" in r.content_md
        assert "帮我做一个 PPT" in r.content_md

    def test_contains_execution_table(self, env) -> None:
        bus, gen, _ = env
        _feed_events(bus)
        r = gen.generate("t-100", "x", _sample_result())
        assert "## 📊 执行详情" in r.content_md
        assert "s1" in r.content_md
        assert "s3" in r.content_md

    def test_contains_analysis_section(self, env) -> None:
        bus, gen, _ = env
        _feed_events(bus)
        r = gen.generate("t-100", "x", _sample_result())
        assert "## 💡 分析" in r.content_md

    def test_contains_conclusion(self, env) -> None:
        bus, gen, _ = env
        _feed_events(bus)
        r = gen.generate("t-100", "x", _sample_result())
        assert "## ✅ 客户结论" in r.content_md

    def test_highlights_for_success(self, env) -> None:
        bus, gen, _ = env
        _feed_events(bus)
        # 改成全成功
        result = _sample_result()
        for r_item in result["results"]:
            r_item["ok"] = True
            r_item["error"] = None
        result["all_ok"] = True
        result["fail_count"] = 0
        r = gen.generate("t-100", "x", result)
        assert "亮点" in r.content_md
        assert "✅" in r.content_md

    def test_risks_for_failure(self, env) -> None:
        bus, gen, _ = env
        _feed_events(bus)
        r = gen.generate("t-100", "x", _sample_result())  # 有 1 失败
        assert "风险" in r.content_md
        assert "⚠️" in r.content_md


# ── 降级 / 异常路径 ───────────────────────────────────────

class TestDegradation:
    def test_pdf_failure_falls_back_to_md_only(self, env, monkeypatch) -> None:
        """reportlab 抛异常 → 只写 md, 不挂."""
        bus, gen, _ = env
        _feed_events(bus)

        def boom(*a, **kw):
            raise RuntimeError("pdf broken")

        monkeypatch.setattr(gen, "_render_pdf", boom)
        r = gen.generate("t-100", "x", _sample_result())
        assert r.md_path is not None
        assert r.pdf_path is None

    def test_no_memory_still_works(self, env) -> None:
        """memory=None → 不挂, 只写文件."""
        bus, gen, _ = env
        # env 已经 memory=None
        _feed_events(bus)
        r = gen.generate("t-100", "x", _sample_result())
        assert r.md_path is not None

    def test_empty_results(self, env) -> None:
        """空 results 列表 → 表格空但报告仍生成."""
        bus, gen, _ = env
        _feed_events(bus)
        r = gen.generate("t-100", "x", {"results": [], "all_ok": True})
        assert r.md_path.exists()


# ── 路径处理 ───────────────────────────────────────────────

class TestPathHandling:
    def test_reports_dir_created(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "reports"
        gen = ReportGenerator(bus=LocalEventBus(), reports_dir=str(nested))
        assert nested.exists()

    def test_task_id_in_filename(self, env) -> None:
        bus, gen, _ = env
        _feed_events(bus)
        r = gen.generate("my-special-id-123", "x", _sample_result("my-special-id-123"))
        assert "my-special-id-123" in r.md_path.name