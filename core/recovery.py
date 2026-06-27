"""Recovery — 容错 ABC (熔断 / 重试 / 降级).

职责:包住"会失败的操作",提供 retry / circuit-breaker / fallback 三种
策略. 修补层 (Repair) 失败 N 次 → 触发 pause point → 走人审.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"       # 正常
    OPEN = "open"           # 熔断,直接拒绝
    HALF_OPEN = "half_open"  # 试探


class RecoveryStrategy(ABC):
    """容错策略. 用法: with strategy.guard(): do_thing()"""

    @abstractmethod
    def guard(
        self,
        op: Callable[[], T],
        *,
        max_retries: int = 3,
        fallback: T | None = None,
    ) -> T:
        """跑 op,失败按策略重试 / 降级 / 熔断."""

    @property
    @abstractmethod
    def state(self) -> CircuitState:
        """当前熔断器状态(给 dashboard 看)."""
