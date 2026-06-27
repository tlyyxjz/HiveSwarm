"""RetryRecovery — 失败重试 N 次,带指数退避. 熔断不实现(MVP 用不到)."""
from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

from core.recovery import CircuitState, RecoveryStrategy

T = TypeVar("T")
_log = logging.getLogger(__name__)


class RetryRecovery(RecoveryStrategy):
    """MVP: 重试 max_retries 次,每次间隔 2^attempt 秒. 不做熔断."""

    def __init__(self, base_delay_s: float = 0.1) -> None:
        self._base = base_delay_s
        self._state = CircuitState.CLOSED

    def guard(
        self,
        op: Callable[[], T],
        *,
        max_retries: int = 3,
        fallback: T | None = None,
    ) -> T:
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                return op()
            except Exception as exc:  # noqa: BLE001 — 重试要兜住所有异常
                last_exc = exc
                if attempt < max_retries - 1:
                    delay = self._base * (2 ** attempt)
                    _log.warning("op failed, retry in %.2fs: %s", delay, exc)
                    time.sleep(delay)
        # 全失败,降级
        if fallback is not None:
            return fallback
        assert last_exc is not None
        raise last_exc

    @property
    def state(self) -> CircuitState:
        return self._state
