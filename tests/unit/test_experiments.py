"""实验机器单测 — 任务集/注入器/runner 机制差异签名/指标/报告."""
from __future__ import annotations

import pytest

from experiments.inject import CATEGORIES, INJECTIONS, by_category, make_hook
from experiments.metrics import compute
from experiments.report import render
from experiments.runner import run_batch, run_one
from experiments.taskset import TASKS, validate


class TestTaskset:
    def test_30_tasks_valid(self):
        val = validate()
        assert val["total"] == 30 and val["unique_ids"] == 30
        assert val["categories"] == {"serial": 10, "branch": 10, "guard": 10}
        assert val["problems"] == []

    def test_all_criteria_compilable(self):
        val = validate()
        assert val["criteria_compilable"] == val["criteria_total"] == 31


class TestInjectors:
    def test_25_points_5_categories(self):
        assert len(INJECTIONS) == 25
        bc = by_category()
        assert set(bc) == set(CATEGORIES)
        assert all(len(v) == 5 for v in bc.values())

    def test_once_injection_fires_once(self):
        fired: set = set()
        hook = make_hook("value.1", fired)
        assert hook("calc", 1, 42) == 43  # 第一发命中
        assert hook("calc", 2, 42) == 42  # 之后干净
        assert hook("other", 1, 42) == 42  # 非靶工具不碰

    def test_persistent_injection_always_fires(self):
        fired: set = set()
        hook = make_hook("shape.1", fired)
        assert isinstance(hook("read_file", 1, "x"), dict)
        assert isinstance(hook("read_file", 2, "y"), dict)

    def test_unknown_injection_is_clean(self):
        assert make_hook("nope", set()) is None


class TestMechanismSignature:
    """机制差异签名 (mock 联调的验收核心): 每类注入的 A/B/C 行为符合设计."""

    def test_clean_all_groups_pass(self):
        for g in ("A", "B", "C"):
            assert run_one("S01", g, "").success

    def test_value_error_only_C_survives(self):
        assert not run_one("S01", "A", "value.1").success
        assert not run_one("S01", "B", "value.1").success
        c = run_one("S01", "C", "value.1")
        assert c.success and c.root_cause_tool == "calc"
        assert "re_observe" in c.recovery_actions

    def test_timeout_B_and_C_survive(self):
        assert not run_one("S01", "A", "timeout.2").success
        assert run_one("S01", "B", "timeout.2").success  # 重试就够
        assert run_one("S01", "C", "timeout.2").success

    def test_shape_error_only_C_survives_via_adapter(self):
        assert not run_one("S01", "A", "shape.1").success
        assert not run_one("S01", "B", "shape.1").success
        c = run_one("S01", "C", "shape.1")
        assert c.success and "swap_adapter" in c.recovery_actions

    def test_chain_break_C_escalates_honestly(self):
        assert not run_one("S01", "A", "chain.3").success
        c = run_one("S01", "C", "chain.3")
        assert not c.success and c.escalated  # 不可自动修复 → 出声上报
        assert "halt_escalate" in c.recovery_actions

    def test_pollution_only_C_survives(self):
        assert not run_one("S01", "A", "pollution.1").success
        c = run_one("S01", "C", "pollution.1")
        assert c.success and c.root_cause_tool == "calc"


class TestMetricsAndReport:
    @staticmethod
    def _mini_traces():
        return [
            run_one("S01", g, inj)
            for g in ("A", "B", "C")
            for inj in ("", "value.1", "timeout.2", "shape.1", "chain.3")
        ]

    def test_metrics_compute_and_bounded(self):
        m = compute(self._mini_traces())
        assert m["taskset_validation"]["total"] == 30
        assert 0.0 <= m["repair_success"]["rate"] <= 1.0
        assert 0.0 <= m["first_localization"]["rate"] <= 1.0
        assert 0.0 <= m["uad"]["rate"] <= 1.0
        assert m["group_success"]["C"]["success"] > m["group_success"]["A"]["success"]

    def test_report_marks_demo_data(self):
        md = render(self._mini_traces(), demo=True)
        assert "演示数据，非实测" in md
        assert "七指标" in md
        assert "口径说明" in md
        assert "已知限制" in md

    def test_report_no_banner_when_real(self):
        md = render(self._mini_traces(), demo=False)
        assert "演示数据" not in md
