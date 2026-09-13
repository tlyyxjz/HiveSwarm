"""causal 测试 — 任务包硬要求: ≥5 步依赖链, 第 2 步被证伪、第 5 步报错,
必须返回"第 2 步"而不是"第 5 步". 另覆盖锥/重跑集合/环路/平局."""
from __future__ import annotations

import pytest

from layers.contract.assertion import Assertion, AssertionKind
from layers.contract.causal import (
    contamination_cone,
    find_root_cause,
    rerun_set,
)
from layers.contract.ledger import AssertionLedger


def _a(aid: str, producer: str) -> Assertion:
    return Assertion(
        aid=aid,
        kind=AssertionKind.POST,
        subject=f"out.{producer}",
        predicate="not_empty",
        validator_name="not_empty",
        producer=producer,
    )


@pytest.fixture()
def ledger5() -> AssertionLedger:
    """5 步链: s1→s2→s3→s4→s5, 断言 a_i 依赖 a_{i-1}, producer=步骤 s_i."""
    led = AssertionLedger()
    for i in range(1, 6):
        led.add(_a(f"a{i}", f"s{i}"))
        if i > 1:
            led.depends_on(f"a{i}", f"a{i-1}")
    return led


class TestRootCauseSearch:
    """任务包验收场景: 第 2 步被证伪, 第 5 步报错 → 根因必须是第 2 步."""

    def test_root_is_second_step_not_fifth(self, ledger5):
        ledger5.falsify("a2", observed_by="s2-check")
        ledger5.falsify("a5", observed_by="s5-check")  # 报错位置在第 5 步
        rc = find_root_cause(ledger5, "a5")
        assert rc is not None
        assert rc.aid == "a2"  # 不是 a5!
        assert rc.distance == 3
        assert rc.path == ("a5", "a4", "a3", "a2")

    def test_symptom_only_returns_symptom(self, ledger5):
        ledger5.falsify("a5", observed_by="s5")
        rc = find_root_cause(ledger5, "a5")
        assert rc is not None and rc.aid == "a5" and rc.distance == 0

    def test_no_falsified_returns_none(self, ledger5):
        assert find_root_cause(ledger5, "a5") is None

    def test_unknown_aid_returns_none(self, ledger5):
        assert find_root_cause(ledger5, "nope") is None

    def test_symptom_not_falsified_but_upstream_is(self, ledger5):
        # 症状未标证伪, 但上游 a2 被证伪 → 仍能找到 a2
        ledger5.falsify("a2", observed_by="s2")
        rc = find_root_cause(ledger5, "a5")
        assert rc is not None and rc.aid == "a2"

    def test_cycle_terminates(self):
        led = AssertionLedger()
        for x in ("x1", "x2"):
            led.add(_a(x, x))
        led.depends_on("x1", "x2")
        led.depends_on("x2", "x1")  # 环
        led.falsify("x1")
        rc = find_root_cause(led, "x2")
        assert rc is not None and rc.aid in {"x1", "x2"}

    def test_diamond_root_is_shared_ancestor(self):
        led = AssertionLedger()
        for i in range(1, 5):
            led.add(_a(f"d{i}", f"t{i}"))
        led.depends_on("d2", "d1")
        led.depends_on("d3", "d1")
        led.depends_on("d4", "d2")
        led.depends_on("d4", "d3")
        led.falsify("d1")
        led.falsify("d4")
        rc = find_root_cause(led, "d4")
        assert rc is not None and rc.aid == "d1" and rc.distance == 2


class TestContaminationCone:
    def test_cone_downstream_only(self, ledger5):
        ledger5.falsify("a2")
        cone = contamination_cone(ledger5, "a2")
        assert cone == {"a2", "a3", "a4", "a5"}  # 不含上游 a1

    def test_cone_is_structural_not_status_based(self, ledger5):
        # 锥 = 根因 + 全部传递下游, 与证伪状态无关: 链头 a1 的锥是全链
        assert contamination_cone(ledger5, "a1") == {"a1", "a2", "a3", "a4", "a5"}

    def test_cone_of_leaf_is_just_itself(self, ledger5):
        assert contamination_cone(ledger5, "a5") == {"a5"}

    def test_cone_unknown_empty(self, ledger5):
        assert contamination_cone(ledger5, "nope") == frozenset()


class TestRerunSet:
    def test_rerun_from_root_onward(self, ledger5):
        ledger5.falsify("a2")
        assert rerun_set(ledger5, "a2") == {"s2", "s3", "s4", "s5"}  # 不含 s1!

    def test_rerun_excludes_unattributed(self, ledger5):
        led = AssertionLedger()
        led.add(_a("b1", ""))  # 无 producer
        led.add(_a("b2", "sB"))
        led.depends_on("b2", "b1")
        led.falsify("b1")
        assert rerun_set(led, "b1") == {"sB"}
