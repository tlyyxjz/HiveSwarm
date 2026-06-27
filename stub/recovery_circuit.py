"""CircuitBreaker stub — 熔断器,Lock 保护共享计数器.

生产替换: stub.recovery_retry.RetryRecovery → stub.recovery_circuit.CircuitBreaker.
        连续 N 次失败 → OPEN 熔断 → 等冷却 → HALF_OPEN 试探 → 成功则 CLOSED.

线程安全: self._failures / self._state / self._opened_at 全部 Lock 保护.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, TypeVar

from core.recovery import CircuitState, RecoveryStrategy

T = TypeVar("T")
_log = logging.getLogger(__name__)


class CircuitBreaker(RecoveryStrategy):
    """熔断器. 状态机: CLOSED → OPEN (连续失败) → HALF_OPEN (冷却后) → CLOSED (试探成功).

    Args:
        failure_threshold: 连续失败 N 次触发熔断
        reset_timeout_s: OPEN 后等多少秒进 HALF_OPEN
        max_retries: 单次 guard 调用内最多重试次数
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout_s: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self._threshold = failure_threshold
        self._reset_after = reset_timeout_s
        self._max_retries = max_retries
        self._lock = threading.Lock()
        self._failures = 0
        self._state: CircuitState = CircuitState.CLOSED
        self._opened_at: float = 0.0

    def _transition_if_needed(self) -> CircuitState:
        """线程内: 检查 OPEN → HALF_OPEN 转换."""
        with self._lock:
            if self._state == CircuitState.OPEN and (time.monotonic() - self._opened_at) >= self._reset_after:
                self._state = CircuitState.HALF_OPEN
                _log.info("circuit: OPEN → HALF_OPEN after %.1fs", self._reset_after)
            return self._state

    def _record_success(self) -> None:
        with self._lock:
            if self._state != CircuitState.CLOSED:
                _log.info("circuit: %s → CLOSED", self._state)
            self._state = CircuitState.CLOSED
            self._failures = 0

    def _record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold and self._state != CircuitState.OPEN:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                _log.warning("circuit: → OPEN (failures=%d)", self._failures)

    @property
    def state(self) -> CircuitState:
        return self._transition_if_needed()

    def guard(
        self,
        op: Callable[[], T],
        *,
        max_retries: int | None = None,
        fallback: T | None = None,
    ) -> T:
        """跑 op. 状态 OPEN 时直接拒绝 (返回 fallback 或抛异常)."""
        retries = self._max_retries if max_retries is None else max_retries
        current = self._transition_if_needed()
        if current == CircuitState.OPEN:
            _log.warning("circuit OPEN, rejecting op")
            if fallback is not None:
                return fallback
            raise RuntimeError("circuit open")

        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                result = op()
                self._record_success()
                return result
            except Exception as exc:  # noqa: BLE001 — 熔断要兜住所有异常
                last_exc = exc
                self._record_failure()
                _log.warning("op failed (attempt %d/%d): %s", attempt + 1, retries, exc, exc_info=True)
        if fallback is not None:
            return fallback
        assert last_exc is not None
        raise last_exc

    def reset(self) -> None:
        """强制重置 (管理用)."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failures = 0
            self._opened_at = 0.0