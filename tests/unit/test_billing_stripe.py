"""Tests for stub.billing_stripe.StripeBilling.

Mock stripe.Charge, 验正常计费 / 余额不足 / 用量查询.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.billing import UsageRecord
from stub.billing_stripe import StripeBilling


def test_stub_implements_abc():
    from core.billing import BillingMeter

    assert set(BillingMeter.__abstractmethods__) <= set(dir(StripeBilling))


def test_record_calls_stripe_charge(tmp_path):
    """正常路径: record 调 stripe.Charge.create."""
    billing = StripeBilling(api_key="sk_test_xxx", price_per_1k_tokens_cents=2.0, fallback_path=tmp_path / "fb.jsonl")

    mock_stripe = MagicMock()
    with patch.dict("sys.modules", {"stripe": mock_stripe}):
        usage = UsageRecord(user_id="alice", skill_name="crawler", input_tokens=1000, output_tokens=2000)
        billing.record(usage)

    mock_stripe.Charge.create.assert_called_once()
    kwargs = mock_stripe.Charge.create.call_args.kwargs
    # 3000 tokens / 1000 * 2.0 cents = 6 cents
    assert kwargs["amount"] == 6
    assert kwargs["currency"] == "usd"
    assert "alice" in kwargs["description"]


def test_record_falls_back_to_local_on_stripe_error(tmp_path):
    """Stripe 异常 → 降级写本地 fallback + local total."""
    billing = StripeBilling(api_key="sk_test_xxx", price_per_1k_tokens_cents=2.0, fallback_path=tmp_path / "fb.jsonl")

    mock_stripe = MagicMock()
    mock_stripe.Charge.create.side_effect = RuntimeError("card declined")
    with patch.dict("sys.modules", {"stripe": mock_stripe}):
        usage = UsageRecord(user_id="alice", skill_name="crawler", input_tokens=1000, output_tokens=1000)
        billing.record(usage)

    # 本地累计 + 文件
    assert billing.usage_for("alice") == 4
    lines = (tmp_path / "fb.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1


def test_usage_for_returns_zero_for_unknown_user(tmp_path):
    """未计费用户 → 0."""
    billing = StripeBilling(api_key="sk_test_xxx", fallback_path=tmp_path / "fb.jsonl")
    assert billing.usage_for("ghost") == 0


def test_record_zero_tokens_no_op(tmp_path):
    """0 token → 不调 Stripe."""
    billing = StripeBilling(api_key="sk_test_xxx", fallback_path=tmp_path / "fb.jsonl")
    mock_stripe = MagicMock()
    with patch.dict("sys.modules", {"stripe": mock_stripe}):
        billing.record(UsageRecord(user_id="alice", skill_name="noop", input_tokens=0, output_tokens=0))
    mock_stripe.Charge.create.assert_not_called()