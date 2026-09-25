"""TypedDispatch + RegressionGate 测试 (榫卯 M2 后半, T1.3).

任务包验收: 五种断言类型各一个 dispatch 单测 + "修 A 坏 B 被闸拦下"用例.
另加 18 组合完备性测试 (3 kind × 6 原语, 不存在不知道该干嘛的格子).
"""
from __future__ import annotations

from layers.contract.assertion import Assertion
from layers.contract.ledger import AssertionLedger, AssertionStatus
from layers.repair.fixer import FixPlan
from layers.repair.regression_gate import RegressionGate
from layers.repair.strategy_table import (
    DISPATCH_TABLE,
    PREDICATE_CLASS,
    TypedDispatch,
)
from layers.repair.typed_fixer import plan_for_symptom


def _assertion(aid: str, kind: str, validator_name: str, producer: str = "") -> Assertion:
    params: dict = {"n": 3} if validator_name in ("min_length", "max_length") else {}
    if validator_name == "in_range":
        params = {"low": 0, "high": 100}
    if validator_name == "regex_match":
        params = {"pattern": r"^\d+$"}
    if validator_name == "has_keys":
        params = {"keys": ["a"]}
    return Assertion(
        aid=aid,
        kind=kind,  # type: ignore[arg-type]
        subject="x",
        predicate="p",
        validator_name=validator_name,
        validator_params=params,
        producer=producer,
    )


class TestDispatchTable:
    """任务包 T1.3 的五行动作, 每行一个单测."""

    def test_all_12_rows_semantics_locked(self):
        """每一格的动作都锁死 (变异测试逼出来的: 只查键不查值会漏掉换行)."""
        expected = {
            ("invariant", "shape"): "halt_escalate",
            ("invariant", "value"): "halt_escalate",
            ("invariant", "threshold"): "halt_escalate",
            ("invariant", "existence"): "halt_escalate",
            ("pre", "shape"): "swap_adapter",
            ("pre", "threshold"): "swap_adapter",
            ("pre", "value"): "re_observe",
            ("pre", "existence"): "re_observe",
            ("post", "threshold"): "swap_skill",
            ("post", "shape"): "re_assemble",
            ("post", "existence"): "re_assemble",
            ("post", "value"): "re_observe",
        }
        assert expected == DISPATCH_TABLE

    def test_shape_error_swaps_adapter(self):
        a = _assertion("p1", "pre", "has_keys")
        assert TypedDispatch().dispatch(a).name == "swap_adapter"

    def test_value_error_reobserves(self):
        a = _assertion("p2", "pre", "in_range")
        assert TypedDispatch().dispatch(a).name == "re_observe"

    def test_threshold_miss_swaps_skill(self):
        a = _assertion("p3", "post", "min_length")
        assert TypedDispatch().dispatch(a).name == "swap_skill"

    def test_intent_mismatch_reassembles(self):
        # post+形状 = 意图表达不对 → 重组
        a = _assertion("p4", "post", "has_keys")
        assert TypedDispatch().dispatch(a).name == "re_assemble"

    def test_invariant_broken_halts_and_escalates(self):
        for vn in PREDICATE_CLASS:
            a = _assertion("p5", "invariant", vn)
            assert TypedDispatch().dispatch(a).name == "halt_escalate", vn

    def test_table_is_complete_no_fallback_cell(self):
        # 3 kind × 6 原语 = 18 组合, 每格唯一动作且都在 5 动作集合内
        actions = set()
        for kind in ("pre", "post", "invariant"):
            for vn in PREDICATE_CLASS:
                key = (kind, PREDICATE_CLASS[vn])
                assert key in DISPATCH_TABLE, key
                actions.add(DISPATCH_TABLE[key])
        assert actions <= {"swap_adapter", "re_observe", "swap_skill", "re_assemble", "halt_escalate"}
        assert len(DISPATCH_TABLE) == 12  # invariant 4 + pre 4 + post 4


class TestEndToEnd:
    def test_symptom_routes_to_root_cause_action(self):
        """5 步链, 第 2 步(post+threshold)被证伪、第 5 步报错 → 动作针对第 2 步."""
        led = AssertionLedger()
        kinds = ["pre", "post", "post", "post", "post"]
        vns = ["not_empty", "min_length", "has_keys", "in_range", "not_empty"]
        for i in range(1, 6):
            led.add(_assertion(f"a{i}", kinds[i - 1], vns[i - 1], producer=f"s{i}"))
            if i > 1:
                led.depends_on(f"a{i}", f"a{i-1}")
        led.falsify("a2")
        led.falsify("a5")  # 报错在第 5 步
        result = TypedDispatch().from_falsified(led, "a5")
        assert result is not None
        action, root_aid = result
        assert root_aid == "a2"
        assert action.name == "swap_skill"  # post+threshold

        plan = plan_for_symptom(led, "a5")
        assert isinstance(plan, FixPlan)
        assert plan.action == "swap_skill"
        assert plan.target_subtask == "s2"  # 根因步, 不是报错步

    def test_no_root_cause_returns_none(self):
        led = AssertionLedger()
        led.add(_assertion("z1", "post", "not_empty"))
        assert plan_for_symptom(led, "z1") is None  # 未证伪 → 无动作

    def test_swap_skill_skills_left_to_upper_layer(self):
        led = AssertionLedger()
        led.add(_assertion("z1", "post", "min_length", producer="s1"))
        led.falsify("z1")
        plan = plan_for_symptom(led, "z1")
        assert plan is not None and plan.new_skills is None  # 不凭空造能力


class TestRegressionGate:
    """修 A 坏 B: 闸必须拦下并记账回滚."""

    def _setup(self) -> tuple[AssertionLedger, dict[str, bool]]:
        led = AssertionLedger()
        led.add(_assertion("v1", "post", "not_empty"))
        led.add(_assertion("v2", "post", "not_empty"))
        led.verify("v1")
        led.verify("v2")
        world = {"v1": True, "v2": True}
        return led, world

    def test_repair_breaks_b_gate_catches(self):
        led, world = self._setup()
        world["v2"] = False  # 修复 A 的副作用: B 坏了
        gate = RegressionGate(led, verify_fn=lambda a: world[a.aid])
        report = gate.gate()
        assert report.needs_rollback
        assert report.broken == (("v2", report.broken[0][1]),)
        rolled = gate.rollback(report, by="repair-A")
        assert rolled == ("v2",)
        assert led.status("v2") is AssertionStatus.FALSIFIED
        assert led.upstream("v2") == set()  # depends_on 无关; invalidates 记在 INVALIDATES 边

    def test_clean_repair_passes_gate(self):
        led, world = self._setup()
        gate = RegressionGate(led, verify_fn=lambda a: world[a.aid])
        assert gate.gate().needs_rollback is False

    def test_verify_fn_crash_counts_as_broken(self):
        led, world = self._setup()

        def boom(a):
            raise RuntimeError("exec environment down")

        gate = RegressionGate(led, verify_fn=boom)
        report = gate.gate()
        assert report.needs_rollback
        assert all("raised" in detail for _aid, detail in report.broken)
        assert gate.rollback(report) == ("v1", "v2")

    def test_unverified_assertions_not_gated(self):
        led = AssertionLedger()
        led.add(_assertion("n1", "post", "not_empty"))  # 从未 verify
        gate = RegressionGate(led, verify_fn=lambda a: False)
        assert gate.gate().broken == ()
