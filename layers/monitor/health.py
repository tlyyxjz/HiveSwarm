"""HealthSnapshot — 整个系统的健康度快照, 供 dashboard 查.

聚合: pool 的 health_report + 事件日志最近 N 条 + LLM judge 最近 score.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.events import EventBus, EventType
from layers.monitor.logger import EventLogger
from layers.work.pool import SkillPool


@dataclass(frozen=True)
class HealthSnapshot:
    """单帧健康度."""

    pool: dict[str, dict[str, Any]]
    recent_events: list[dict[str, Any]]
    error_count: int
    ok_count: int
    timestamp: float  # 简化: 0 = static, time.time() = real


class HealthSnapshotter:
    """打快照."""

    def __init__(self, pool: SkillPool, bus: EventBus, log: EventLogger | None = None) -> None:
        self._pool = pool
        self._bus = bus
        self._log = log

    def snapshot(self, event_window: int = 50) -> HealthSnapshot:
        """打一帧."""
        pool_report = self._pool.health_report()
        recent = self._bus.recent(event_window)
        if self._log is not None:
            # 也可从 log 读 (更多历史)
            try:
                recent = self._log.read_recent(event_window)
            except Exception:  # noqa: BLE001
                pass

        # 统计: 事件里把 TASK_COMPLETED 算 ok, TASK_FAILED 算 error
        ok = sum(1 for e in recent if e.get("type") == EventType.TASK_COMPLETED.value)
        err = sum(1 for e in recent if e.get("type") == EventType.TASK_FAILED.value)
        import time

        return HealthSnapshot(
            pool=pool_report,
            recent_events=recent,
            error_count=err,
            ok_count=ok,
            timestamp=time.time(),
        )
