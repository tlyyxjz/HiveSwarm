"""EventBus — 跨层事件总线 ABC.

职责:Monitor 监听所有事件,其他层 publish. 修一个事件类型 = 加一个
enum,Bus 实现只管发收,不分发逻辑(那在 Monitor).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable


class EventType(str, Enum):
    SKILL_CHECKED_OUT = "skill.checked_out"
    SKILL_RETURNED = "skill.returned"
    AGENT_ASSEMBLED = "agent.assembled"
    AGENT_DESTROYED = "agent.destroyed"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    REPAIR_TRIGGERED = "repair.triggered"
    PAUSE_POINT = "pause.point"  # 通知人审


@dataclass(frozen=True)
class Event:
    type: EventType
    payload: dict[str, Any]
    ts: datetime = datetime.now()  # 不可变 + 自动时间戳

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type.value, "ts": self.ts.isoformat(), **self.payload}


Subscriber = Callable[[Event], None]


class EventBus(ABC):
    """事件总线. subscribe 收 publish 发."""

    @abstractmethod
    def publish(self, event: Event) -> None:
        """发事件. 同步触发所有 subscriber."""

    @abstractmethod
    def subscribe(self, event_type: EventType, fn: Subscriber) -> int:
        """订阅事件类型. 返回 sub_id, 之后调 unsubscribe 用."""

    @abstractmethod
    def unsubscribe(self, event_type: EventType, sub_id: int) -> None:
        """取消订阅. 幂等, 不存在的 sub_id 不报错."""

    @abstractmethod
    def replay(self, since_ts: datetime | None = None) -> list[Event]:
        """时间旅行回放(从 append-only log 重放)."""
