"""Telemetry — 链路追踪 ABC.

职责:trace / span / metric,排查"哪个 skill 慢"用. MVP noop,公司里接
OpenTelemetry / Datadog.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Iterator


class Tracer(ABC):
    """分布式追踪."""

    @contextmanager
    @abstractmethod
    def span(self, name: str, **attrs: object) -> Iterator[None]:
        """开一个 span,内部代码跑完自动 close. yield None 给用户用 with."""

    @abstractmethod
    def metric_inc(self, name: str, value: int = 1, **tags: str) -> None:
        """计数器 +N."""

    @abstractmethod
    def metric_observe(self, name: str, value_ms: float, **tags: str) -> None:
        """直方图(看 P50/P95)."""
