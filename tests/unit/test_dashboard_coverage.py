"""覆盖率补测 (T3.3): GradioDashboard 的纯逻辑方法 (渲染/分类/快照), 不启 server."""
from __future__ import annotations

import asyncio
import json

import pytest

from core.events import Event, EventType
from stub.bus_local import LocalEventBus
from stub.dashboard_gradio import GradioDashboard
from stub.store_sqlite import SQLiteStore


@pytest.fixture()
def dash(tmp_path):
    pool = None  # 渲染方法对 None pool 都要能扛 (空仓状态)
    bus = LocalEventBus()
    d = GradioDashboard(
        pool=pool, bus=bus,
        log_path=tmp_path / "logs" / "events.jsonl",
        reports_dir=tmp_path / "reports",
    )
    return d, bus


class TestClassifyError:
    def test_network_class(self, dash):
        d, _ = dash
        html, cls = d._classify_error(ConnectionError("down"))
        assert cls == "error-net" and "Network Error" in html

    def test_param_class(self, dash):
        d, _ = dash
        html, cls = d._classify_error(KeyError("missing"))
        assert cls == "error-param" and "Parameter Error" in html

    def test_system_class_default(self, dash):
        d, _ = dash
        html, cls = d._classify_error(RuntimeError("boom"))
        assert cls == "error-system" and "System Error" in html


class TestThemeAndSnapshot:
    def test_toggle_theme(self, dash):
        d, _ = dash
        before = d._theme_mode
        new = d._toggle_theme(before)
        assert new in ("light", "dark") and new != before
        assert d._theme_mode == new  # 状态跟着翻转到返回值

    def test_snapshot_without_pool(self, dash):
        d, _ = dash
        snap = d.snapshot()
        assert snap["skills"] == 0 and snap["port"] == d.port

    def test_snapshot_with_pool(self, tmp_path):
        from layers.work.pool import SkillPool
        from stub.dashboard_gradio import GradioDashboard as GD

        pool = SkillPool()
        from core.skill import Skill, SkillManifest

        class S(Skill):
            def __init__(self):
                super().__init__(SkillManifest(name="s1", api_version="1.0"))
            def run(self, input_data):
                return {}
        pool.register(S())
        d = GD(pool=pool, log_path=tmp_path / "l.jsonl", reports_dir=tmp_path / "r")
        assert d.snapshot()["skills"] == 1


class TestRenderersOnEmptyState:
    """空仓状态下所有渲染方法不许炸 (陌生人第一眼的鲁棒性)."""

    def test_renderers_run_clean(self, dash):
        d, _ = dash
        assert isinstance(d._render_statusbar(), str)
        assert isinstance(d._render_skills(), list)
        assert isinstance(d._render_tasks(), list)
        assert isinstance(d._render_events(), str)
        assert isinstance(d._render_brain(), list)
        assert isinstance(d._render_repair(), str)
        assert isinstance(d._render_memory(), str)
        assert isinstance(d._render_inspect(), list)
        assert isinstance(d._render_reports_list(), list)
        assert isinstance(d._render_health(), str)

    def test_renderers_with_events(self, dash):
        d, bus = dash
        bus.publish(Event(type=EventType.TASK_STARTED, payload={"task_id": "t1"}))
        bus.publish(Event(type=EventType.TASK_COMPLETED, payload={"task_id": "t1"}))
        assert isinstance(d._render_events(), str)
        rows = d._render_brain()
        assert isinstance(rows, list)
