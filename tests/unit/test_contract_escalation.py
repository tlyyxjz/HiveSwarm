"""VerificationLadder 测试 (榫卯 M3, T1.4).

任务包验收: 跑 10 轮 —— 验证等级随连续稳定次数自动上升, 被证伪后自动回落.
"""
from __future__ import annotations

import pytest

from core.events import EventType
from layers.contract.assertion import Assertion, AssertionKind, AssertionStatus
from layers.contract.escalation import VerificationLadder
from layers.contract.ledger import AssertionLedger


def _a(aid: str, level: int = 1) -> Assertion:
    return Assertion(
        aid=aid,
        kind=AssertionKind.POST,
        subject="out.count",
        predicate="in:0,100",
        validator_name="in_range",
        validator_params={"low": 0, "high": 100},
        level=level,
        producer="s1",
    )


@pytest.fixture()
def env():
    led = AssertionLedger()
    led.add(_a("e1"))
    events: list = []
    ladder = VerificationLadder(led, promote_after=3, emit=events.append)
    return led, ladder, events


class TestTenRoundScenario:
    def test_10_round_promote_then_falsify(self, env):
        """任务包验收主线: 升级曲线 + 证伪回落, 全程事件可审计."""
        led, ladder, events = env
        levels = []
        for r in range(1, 11):
            ok = r <= 6  # 前 6 轮通过, 第 7 轮证伪, 后 3 轮尝试复验(不回翻)
            ladder.observe("e1", ok=ok)
            levels.append(led.get("e1").level)
        assert levels == [1, 1, 2, 2, 2, 2, 1, 1, 1, 1]  # 第3轮升, 第7轮降回
        types = [e.type for e in events]
        assert EventType.ASSERTION_ESCALATED in types
        assert EventType.ASSERTION_FALSIFIED in types
        assert EventType.ASSERTION_DEGRADED in types
        assert types.index(EventType.ASSERTION_ESCALATED) < types.index(EventType.ASSERTION_FALSIFIED)
        # 证伪是终态: 后续复验不再通过, 等级停在 L1
        assert led.status("e1") is AssertionStatus.FALSIFIED
        assert ladder.observe("e1", ok=True).transition == "terminal_falsified"

    def test_promotion_threshold_not_met_early(self, env):
        led, ladder, events = env
        ladder.observe("e1", ok=True)
        ladder.observe("e1", ok=True)
        assert led.get("e1").level == 1  # 2 次不够 N=3, 不许升
        assert EventType.ASSERTION_ESCALATED not in [e.type for e in events]
        assert led.pass_count("e1") == 2

    def test_falsify_before_promotion_stays_l1(self, env):
        led, ladder, events = env
        ladder.observe("e1", ok=True)
        ladder.observe("e1", ok=False)  # 还没升过, 证伪不触发降级(已在 L1)
        assert led.get("e1").level == 1
        assert EventType.ASSERTION_DEGRADED not in [e.type for e in events]
        assert EventType.ASSERTION_FALSIFIED in [e.type for e in events]
        assert led.pass_count("e1") == 0  # 证伪清零连续计数


class TestLevelSemantics:
    def test_l0_not_verifiable(self):
        led = AssertionLedger()
        led.add(_a("l0", level=0))
        ladder = VerificationLadder(led)
        out = ladder.observe("l0", ok=True)
        assert out.transition == "not_verifiable"
        assert led.status("l0") is AssertionStatus.UNVERIFIED  # 状态被动过没有? 没动

    def test_l3_manual_only_degrades_on_falsify(self):
        led = AssertionLedger()
        led.add(_a("l3", level=3))
        ladder = VerificationLadder(led, promote_after=1)
        ladder.observe("l3", ok=True)  # pass_count=1 >= 1, 但 L3 不自动升降
        assert led.get("l3").level == 3
        ladder.observe("l3", ok=False)  # 证伪 → 降回 L1 (降级规则对所有 >1 生效)
        assert led.get("l3").level == 1
        assert led.status("l3") is AssertionStatus.FALSIFIED

    def test_l2_stays_l2_on_more_passes(self, env):
        led, ladder, events = env
        for _ in range(3):
            ladder.observe("e1", ok=True)
        assert led.get("e1").level == 2
        ladder.observe("e1", ok=True)
        ladder.observe("e1", ok=True)
        assert led.get("e1").level == 2  # 不自动到 L3 (L3 人工设定)

    def test_custom_promote_after(self):
        led = AssertionLedger()
        led.add(_a("c1"))
        ladder = VerificationLadder(led, promote_after=1)
        ladder.observe("c1", ok=True)
        assert led.get("c1").level == 2

    def test_invalid_promote_after_rejected(self):
        with pytest.raises(ValueError):
            VerificationLadder(AssertionLedger(), promote_after=0)

    def test_unknown_aid_returns_none(self, env):
        led, ladder, _events = env
        assert ladder.observe("nope", ok=True) is None
