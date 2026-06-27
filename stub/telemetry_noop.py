"""NoopTelemetry — 不发任何东西. 换 OpenTelemetry 时改 1 行配置."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from core.telemetry import Tracer


class NoopTelemetry(Tracer):
    """MVP: 啥都不发. 接口全实现,行为全 noop."""

    @contextmanager
    def span(self, name: str, **attrs: object) -> Iterator[None]:
        yield  # 啥也不干,直接过

    def metric_inc(self, name: str, value: int = 1, **tags: str) -> None:
        return

    def metric_observe(self, name: str, value_ms: float, **tags: str) -> None:
        return
