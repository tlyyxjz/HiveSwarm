"""AssertionLedger 测试 — 依赖图构建 + 证伪记账(只记账不打断) + 状态机."""
from __future__ import annotations

import pytest

from layers.contract.assertion import Assertion, AssertionKind, AssertionStatus
from layers.contract.ledger import AssertionLedger, EdgeType


def _a(aid: str, subject: str = "x") -> Assertion:
    return Assertion(
        aid=aid,
        kind=AssertionKind.PRE,
        subject=subject,
        predicate="not_empty",
        validator_name="not_empty",
    )


@pytest.fixture()
def chain() -> AssertionLedger:
    """5 步依赖链: a1 ← a2 ← a3 ← a4 ← a5 (a2 依赖 a1, 以此类推)."""
    led = AssertionLedger()
    for i in range(1, 6):
        led.add(_a(f"a{i}"))
        if i > 1:
            led.depends_on(f"a{i}", f"a{i-1}")
    return led


class TestGraphConstruction:
    def test_add_and_get(self, chain):
        assert chain.has("a3")
        assert chain.get("a3").aid == "a3"
        assert chain.status("a3") is AssertionStatus.UNVERIFIED

    def test_duplicate_aid_raises(self, chain):
        with pytest.raises(ValueError, match="duplicate"):
            chain.add(_a("a1"))

    def test_unknown_aid_get_raises_status_none(self, chain):
        with pytest.raises(KeyError):
            chain.get("nope")
        assert chain.status("nope") is None

    def test_depends_on_edges(self, chain):
        # 边方向约定: src --depends_on--> dst 表示 src 依赖 dst
        assert chain.downstream("a2") == {"a1"}  # a2 依赖 a1 (回追根因方向)
        assert chain.upstream("a2") == {"a3"}  # a3 依赖 a2 (污染锥方向)
        assert chain.downstream("a1") == set()  # 链头无前置
        # T1.2 将使用的无歧义别名, 语义同上
        assert chain.prerequisites("a3") == {"a2"}
        assert chain.dependents("a1") == {"a2"}

    def test_derive_and_trigger_edges(self, chain):
        chain.derives_from("a3", "a1")
        chain.triggered("a3", "action_swap_skill")
        assert chain.downstream("a3", EdgeType.DERIVE) == {"a1"}  # a3 源自 a1
        assert chain.upstream("a1", EdgeType.DERIVE) == {"a3"}
        assert chain.downstream("a3", EdgeType.TRIGGER) == {"action_swap_skill"}


class TestFalsify:
    """证伪只记账、不打断执行流: 任何输入都不许 raise."""

    def test_falsify_sets_status_and_logs(self, chain):
        rec = chain.falsify("a2", observed_by="obs-step5")
        assert rec is not None
        assert chain.status("a2") is AssertionStatus.FALSIFIED
        assert rec.aid == "a2"
        assert rec.observed_by == "obs-step5"
        assert len(chain.falsification_log()) == 1

    def test_falsify_records_invalidates_edge(self, chain):
        chain.falsify("a2", observed_by="obs-step5")
        assert chain.upstream("a2", EdgeType.INVALIDATES) == {"obs-step5"}

    def test_falsify_unknown_aid_returns_none_never_raises(self, chain):
        assert chain.falsify("does-not-exist") is None  # 不打断执行流

    def test_falsify_idempotent_returns_first_record(self, chain):
        r1 = chain.falsify("a2", observed_by="o1")
        r2 = chain.falsify("a2", observed_by="o2")  # 第二次观测重复证伪
        assert r1 is r2  # 幂等: 返回首次记录
        assert len(chain.falsification_log()) == 1

    def test_falsify_without_observer_skips_edge(self, chain):
        chain.falsify("a2")
        assert chain.upstream("a2", EdgeType.INVALIDATES) == set()


class TestVerify:
    def test_verify_transitions_and_counts(self, chain):
        assert chain.verify("a1") is True
        assert chain.status("a1") is AssertionStatus.VERIFIED
        chain.verify("a1")
        chain.verify("a1")
        assert chain.pass_count("a1") == 3  # M3 阶梯的原始计数

    def test_verify_unknown_aid_false(self, chain):
        assert chain.verify("nope") is False

    def test_falsified_is_terminal(self, chain):
        chain.verify("a1")
        chain.verify("a1")
        chain.falsify("a1", observed_by="o")
        assert chain.pass_count("a1") == 0  # 证伪清零"连续通过"
        assert chain.verify("a1") is False  # 不回翻
        assert chain.status("a1") is AssertionStatus.FALSIFIED


class TestChainScenario:
    """T1.2 的前置场景预演: 链上第 2 步被证伪, 账本状态与日志一致."""

    def test_5step_chain_falsify_second(self, chain):
        for i in (1, 3, 4, 5):  # 其余各步都验过
            chain.verify(f"a{i}")
        chain.falsify("a2", observed_by="step-5-check")
        assert chain.status("a2") is AssertionStatus.FALSIFIED
        assert chain.status("a1") is AssertionStatus.VERIFIED
        # 报错发生在第 5 步, 但账本记录的根因候选在第 2 步 (反向搜索在 T1.2)
        log = chain.falsification_log()
        assert len(log) == 1 and log[0].aid == "a2"
