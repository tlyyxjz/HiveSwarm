"""LocalEventBus — 进程内 pub/sub + 内存 replay. 换 Kafka 时改 1 行配置."""
from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime
from typing import Any

from core.events import Event, EventBus, EventType, Subscriber


class LocalEventBus(EventBus):
    """MVP: 进程内事件总线,带 append-only 内存 log 支持 replay."""

    def __init__(self, max_log: int = 10000) -> None:
        self._subs: dict[EventType, list[tuple[int, Subscriber]]] = defaultdict(list)
        self._log: list[Event] = []
        self._max_log = max_log
        self._lock = threading.Lock()

    def publish(self, event: Event) -> None:
        with self._lock:
            # append-only log
            self._log.append(event)
            if len(self._log) > self._max_log:
                self._log = self._log[-self._max_log :]
        # subscriber 调用要在锁外(避免死锁)
        for _sid, fn in list(self._subs.get(event.type, [])):
            try:
                fn(event)
            except Exception:  # noqa: BLE001 — subscriber 失败不影响 bus
                pass

    def subscribe(self, event_type: EventType, fn: Subscriber) -> int:
        """Subscribe fn to event_type. Returns unique sub_id for later unsubscribe."""
        with self._lock:
            sub_id = id(fn)
            self._subs[event_type].append((sub_id, fn))
            return sub_id

    def unsubscribe(self, event_type: EventType, sub_id: int) -> None:
        """Remove subscriber by id. 幂等."""
        with self._lock:
            self._subs[event_type] = [
                (sid, fn) for sid, fn in self._subs[event_type] if sid != sub_id
            ]

    def replay(self, since_ts: datetime | None = None) -> list[Event]:
        if since_ts is None:
            return list(self._log)
        return [e for e in self._log if e.ts >= since_ts]

    def recent(self, n: int = 50, type_: EventType | None = None) -> list[dict[str, Any]]:
        """方便 dashboard 取最近 N 条(已序列化)."""
        out = [e for e in self._log[-n:] if type_ is None or e.type == type_]
        return [e.to_dict() for e in out]
