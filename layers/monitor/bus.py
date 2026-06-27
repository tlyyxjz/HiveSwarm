"""MonitorBus — 把 EventBus 接 EventLogger, 顺便做"事件 → 写盘" + "事件 → bus 转发".

用法:
    raw_bus = LocalEventBus()
    log = EventLogger("/tmp/events.jsonl")
    monitor = MonitorBus(raw_bus, log)
    raw_bus.subscribe(EventType.TASK_STARTED, monitor.forward)  # 自动写盘
"""
from __future__ import annotations

from core.events import Event, EventBus, EventType
from layers.monitor.logger import EventLogger


class MonitorBus:
    """把事件总线 + 日志粘合. 单一职责."""

    def __init__(self, bus: EventBus, logger: EventLogger) -> None:
        self._bus = bus
        self._log = logger
        self._subscribed: list[EventType] = []

    def attach(self) -> None:
        """订阅所有事件, 转发到日志. 调多次幂等."""
        for et in EventType:
            if et not in self._subscribed:
                self._bus.subscribe(et, self._log.write)
                self._subscribed.append(et)

    def forward(self, event: Event) -> None:
        """给其他 subscriber 用的 forward 钩子. 这里直接写盘."""
        self._log.write(event)

    @property
    def log_path(self):
        return self._log._path
