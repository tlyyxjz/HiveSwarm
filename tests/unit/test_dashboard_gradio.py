"""Dashboard 新加的 4 个 Tab + 5 个图表数据源 — 防回归."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from core.events import Event, EventType
from core.skill import Skill, SkillManifest, SkillHealth
from layers.memory.store import MemoryStore, MemoryTier
from stub.bus_local import LocalEventBus
from stub.dashboard_gradio import GradioDashboard
from stub.store_sqlite import SQLiteStore
from layers.work.pool import SkillPool


class FakeSkill(Skill):
    def __init__(self, name: str, fail: bool = False) -> None:
        super().__init__(SkillManifest(name=name, api_version="1.0", description=f"fake {name}"))
        self._fail = fail

    def run(self, input_data):
        if self._fail:
            raise ValueError(f"{self.manifest.name} simulated failure")
        return {"ok": True, "name": self.manifest.name, "echo": input_data}

    async def health_check(self):
        return SkillHealth(name=self.manifest.name, success_count=1)


@pytest.fixture
def full_env(tmp_path: Path):
    """完整 mock 环境: pool + bus + memory."""
    bus = LocalEventBus()
    pool = SkillPool(bus=bus)
    pool.register(FakeSkill("alpha"))
    pool.register(FakeSkill("beta", fail=True))

    # 多塞事件
    import time
    for i in range(3):
        bus.publish(Event(type=EventType.TASK_STARTED, payload={
            "task_id": f"t-{i}", "rationale": f"test {i}", "subtasks": [1, 2, 3]
        }))
        time.sleep(0.001)
    bus.publish(Event(type=EventType.TASK_COMPLETED, payload={"task_id": "t-0"}))
    bus.publish(Event(type=EventType.TASK_COMPLETED, payload={"task_id": "t-1"}))
    bus.publish(Event(type=EventType.TASK_FAILED, payload={
        "task_id": "t-2", "subtask_id": "s-2", "error": "boom"
    }))
    bus.publish(Event(type=EventType.REPAIR_TRIGGERED, payload={
        "task_id": "t-2", "subtask_id": "s-2", "action": "switch_skill"
    }))

    db = tmp_path / "mem.db"
    mem = MemoryStore(SQLiteStore(db))
    mem.put(MemoryTier.LONG, "task:t-0", {"ok": True, "r": "all passed"})
    mem.put(MemoryTier.SHORT, "session:c", {"user": "demo"})
    mem.put(MemoryTier.WORKING, "plan:0", {"subtasks": 3})

    dash = GradioDashboard(pool=pool, bus=bus, brain=None, memory=mem)
    return dash


# ── Brain Tab (DataFrame 7 列) ──────────────────────────────

class TestRenderBrain:
    def test_returns_7_columns(self, full_env: GradioDashboard) -> None:
        rows = full_env._render_brain()
        assert len(rows) > 0
        assert len(rows[0]) == 7

    def test_columns_order(self, full_env: GradioDashboard) -> None:
        rows = full_env._render_brain()
        # Time / Task ID / Subs / Status / Dur / Rationale / Skills
        assert "t-0" in rows[0][1]
        assert rows[0][2] == 3  # subtasks count

    def test_status_pass_for_completed(self, full_env: GradioDashboard) -> None:
        rows = full_env._render_brain()
        # 找 t-0 (completed) 应该 PASS
        t0_rows = [r for r in rows if r[1] == "t-0"]
        assert len(t0_rows) >= 1
        assert t0_rows[0][3] == "PASS"

    def test_no_bus_returns_placeholder(self, tmp_path: Path) -> None:
        dash = GradioDashboard(pool=None, bus=None, brain=None, memory=None)
        rows = dash._render_brain()
        assert "error" in rows[0][0]


# ── Repair Tab (Markdown 流) ───────────────────────────────

class TestRenderRepair:
    def test_includes_failure_and_action(self, full_env: GradioDashboard) -> None:
        md = full_env._render_repair()
        assert "FAIL" in md
        assert "switch_skill" in md
        # 失败事件的 subtask_id "s-2" 优先于 task_id "t-2"
        assert "s-2" in md

    def test_counts_failures_and_repairs(self, full_env: GradioDashboard) -> None:
        md = full_env._render_repair()
        assert "Failures**: 1" in md
        assert "Repairs**: 1" in md

    def test_action_statistics(self, full_env: GradioDashboard) -> None:
        md = full_env._render_repair()
        assert "switch_skill=1" in md

    def test_no_bus_returns_placeholder(self, tmp_path: Path) -> None:
        dash = GradioDashboard(pool=None, bus=None, brain=None, memory=None)
        assert dash._render_repair() == "Bus not connected"


# ── Memory Tab (Markdown table 4 列) ───────────────────────

class TestRenderMemory:
    def test_includes_tier_table(self, full_env: GradioDashboard) -> None:
        md = full_env._render_memory()
        assert "| Tier |" in md
        assert "long" in md
        assert "short" in md
        assert "working" in md

    def test_sample_value_visible(self, full_env: GradioDashboard) -> None:
        md = full_env._render_memory()
        # value 缩略包含键名
        assert "ok" in md or "user" in md or "subtasks" in md

    def test_total_count(self, full_env: GradioDashboard) -> None:
        md = full_env._render_memory()
        assert "Total**: 3" in md

    def test_no_memory_returns_placeholder(self, tmp_path: Path) -> None:
        dash = GradioDashboard(pool=None, bus=None, brain=None, memory=None)
        assert "not connected" in dash._render_memory()


# ── Inspect Tab (DataFrame 7 列) ───────────────────────────

class TestRenderInspect:
    def test_returns_7_columns(self, full_env: GradioDashboard) -> None:
        rows = full_env._render_inspect()
        assert len(rows) > 0
        assert len(rows[0]) == 7

    def test_pass_task_has_rate_100(self, full_env: GradioDashboard) -> None:
        rows = full_env._render_inspect()
        t0 = [r for r in rows if r[1] == "t-0"]
        assert len(t0) >= 1
        assert t0[0][3] == 1  # OK
        assert t0[0][4] == 0  # Fail
        assert t0[0][5] == "100.0%"
        assert t0[0][6] == "PASS"

    def test_fail_task_verdict(self, full_env: GradioDashboard) -> None:
        rows = full_env._render_inspect()
        t2 = [r for r in rows if r[1] == "t-2"]
        assert len(t2) >= 1
        assert t2[0][6] == "FAIL"


# ── Charts: 5 个数据源 (返回 pd.DataFrame) ──────────────────

class TestChartDataSources:
    def test_skill_refcount_returns_dataframe(self, full_env: GradioDashboard) -> None:
        df = full_env._render_skill_refcount()
        assert isinstance(df, pd.DataFrame)
        assert "Skill" in df.columns
        assert "Refcount" in df.columns
        assert len(df) == 2  # alpha + beta

    def test_skill_health_returns_dataframe(self, full_env: GradioDashboard) -> None:
        df = full_env._render_skill_health()
        assert isinstance(df, pd.DataFrame)
        assert {"Skill", "Success", "Failure"}.issubset(df.columns)

    def test_event_timeline_returns_dataframe(self, full_env: GradioDashboard) -> None:
        df = full_env._render_event_timeline()
        assert isinstance(df, pd.DataFrame)
        assert {"minute", "count"}.issubset(df.columns)
        # 我们的事件都在同一分钟
        assert len(df) >= 1

    def test_event_type_pie_returns_dataframe(self, full_env: GradioDashboard) -> None:
        df = full_env._render_event_type_pie()
        assert isinstance(df, pd.DataFrame)
        assert {"type", "count"}.issubset(df.columns)
        # 应该至少包含 started/completed/failed/triggered
        types = set(df["type"])
        assert "started" in types
        assert "completed" in types
        assert "failed" in types

    def test_task_success_rate_returns_dataframe(self, full_env: GradioDashboard) -> None:
        df = full_env._render_task_success_rate()
        assert isinstance(df, pd.DataFrame)
        assert {"minute", "ok", "fail", "rate"}.issubset(df.columns)

    def test_chart_handles_no_pool_or_bus(self, tmp_path: Path) -> None:
        dash = GradioDashboard(pool=None, bus=None, brain=None, memory=None)
        # 应不抛异常, 返回空/默认 DataFrame
        assert isinstance(dash._render_skill_refcount(), pd.DataFrame)
        assert isinstance(dash._render_skill_health(), pd.DataFrame)
        assert isinstance(dash._render_event_timeline(), pd.DataFrame)
        assert isinstance(dash._render_event_type_pie(), pd.DataFrame)
        assert isinstance(dash._render_task_success_rate(), pd.DataFrame)


# ── Reports Tab ────────────────────────────────────────────

class TestReportsTab:
    def test_empty_reports_dir_returns_placeholder(self, tmp_path: Path) -> None:
        dash = GradioDashboard(
            pool=None, bus=None, brain=None, memory=None,
            reports_dir=str(tmp_path / "empty"),
        )
        rows = dash._render_reports_list()
        assert rows[0][0] == "—"

    def test_lists_markdown_files(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        (reports_dir / "t-100.md").write_text("# T1", encoding="utf-8")
        (reports_dir / "t-200.md").write_text("# T2", encoding="utf-8")
        dash = GradioDashboard(
            pool=None, bus=None, brain=None, memory=None,
            reports_dir=str(reports_dir),
        )
        rows = dash._render_reports_list()
        assert len(rows) == 2
        filenames = {r[0] for r in rows}
        assert filenames == {"t-100.md", "t-200.md"}

    def test_detects_pdf_presence(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        (reports_dir / "t-1.md").write_text("# T", encoding="utf-8")
        (reports_dir / "t-1.pdf").write_bytes(b"%PDF-1.4 fake")
        (reports_dir / "t-2.md").write_text("# T", encoding="utf-8")
        dash = GradioDashboard(
            pool=None, bus=None, brain=None, memory=None,
            reports_dir=str(reports_dir),
        )
        rows = dash._render_reports_list()
        by_name = {r[0]: r for r in rows}
        assert by_name["t-1.md"][4] == "PDF"
        assert by_name["t-2.md"][4] == "—"

    def test_extracts_task_id_from_filename(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        (reports_dir / "t-my-special-task.md").write_text("# X", encoding="utf-8")
        dash = GradioDashboard(
            pool=None, bus=None, brain=None, memory=None,
            reports_dir=str(reports_dir),
        )
        rows = dash._render_reports_list()
        assert rows[0][1] == "my-special-task"

    def test_render_content_reads_file(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        (reports_dir / "t-x.md").write_text("# Hello\nWorld", encoding="utf-8")
        dash = GradioDashboard(
            pool=None, bus=None, brain=None, memory=None,
            reports_dir=str(reports_dir),
        )
        content = dash._render_report_content("t-x.md")
        assert "# Hello" in content
        assert "World" in content

    def test_render_content_handles_dataframe_selection(self, tmp_path: Path) -> None:
        """Dataframe 选中返回 list-of-list, render_content 要正确处理."""
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        (reports_dir / "t-y.md").write_text("# Y", encoding="utf-8")
        dash = GradioDashboard(
            pool=None, bus=None, brain=None, memory=None,
            reports_dir=str(reports_dir),
        )
        # 模拟 Gradio Dataframe 选中格式
        content = dash._render_report_content([["t-y.md", "y", "2026", "100B", "—"]])
        assert "# Y" in content

    def test_render_content_missing_file(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        dash = GradioDashboard(
            pool=None, bus=None, brain=None, memory=None,
            reports_dir=str(reports_dir),
        )
        content = dash._render_report_content("nonexistent.md")
        assert "不存在" in content

    def test_render_content_empty_selection(self, tmp_path: Path) -> None:
        dash = GradioDashboard(
            pool=None, bus=None, brain=None, memory=None,
            reports_dir=str(tmp_path / "empty"),
        )
        assert "请选择" in dash._render_report_content(None)
        assert "请选择" in dash._render_report_content([])