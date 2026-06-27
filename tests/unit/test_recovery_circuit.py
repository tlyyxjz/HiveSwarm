"""Tests for stub.recovery_circuit.CircuitBreaker.

验: 正常路径 / 连续 5 次失败触发熔断 / 半开恢复.
"""
from __future__ import annotations

import pytest

from core.recovery import CircuitState
from stub.recovery_circuit import CircuitBreaker


def test_stub_implements_abc():
    from core.recovery import RecoveryStrategy

    assert set(RecoveryStrategy.__abstractmethods__) <= set(dir(CircuitBreaker))


def test_guard_normal_returns_value():
    """正常 op → 直接返回."""
    cb = CircuitBreaker(failure_threshold=5, reset_timeout_s=30.0, max_retries=3)
    result = cb.guard(lambda: 42)
    assert result == 42
    assert cb.state == CircuitState.CLOSED


def test_guard_opens_after_threshold_failures():
    """连续 5 次失败 → 状态变 OPEN."""
    cb = CircuitBreaker(failure_threshold=5, reset_timeout_s=30.0, max_retries=1)

    def boom() -> None:
        raise RuntimeError("service down")

    # 5 次失败 (max_retries=1 → 每次 guard 调一次 op)
    for _ in range(5):
        with pytest.raises(RuntimeError):
            cb.guard(boom)

    assert cb.state == CircuitState.OPEN

    # OPEN 后第 6 次调用直接拒绝 (fallback 返回)
    result = cb.guard(boom, fallback="rejected")
    assert result == "rejected"


def test_guard_recovers_via_half_open():
    """冷却后 HALF_OPEN → 试探成功 → CLOSED."""
    cb = CircuitBreaker(failure_threshold=3, reset_timeout_s=0.05, max_retries=1)

    # 触发熔断
    for _ in range(3):
        with pytest.raises(RuntimeError):
            cb.guard(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
    assert cb.state == CircuitState.OPEN

    # 冷却
    import time
    time.sleep(0.06)

    # HALF_OPEN 试探成功
    result = cb.guard(lambda: "ok")
    assert result == "ok"
    assert cb.state == CircuitState.CLOSED


def test_guard_falls_back_after_retries_exhausted():
    """max_retries 用尽 → 返回 fallback (无熔断触发)."""
    cb = CircuitBreaker(failure_threshold=10, max_retries=2)

    def boom() -> None:
        raise ValueError("err")

    result = cb.guard(boom, fallback="safe")
    assert result == "safe"


def test_reset_force_closes():
    """reset() 强制回 CLOSED."""
    cb = CircuitBreaker(failure_threshold=2, max_retries=1)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            cb.guard(lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert cb.state == CircuitState.OPEN
    cb.reset()
    assert cb.state == CircuitState.CLOSED