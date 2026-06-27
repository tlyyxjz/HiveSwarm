"""EventLogger — append-only JSONL 写盘 + 读回.

跟 stub/audit_logfile 一样套路, 但这是给 EventBus 用的 (结构化事件).
失败不能阻塞主流程.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from core.events import Event, EventType

_log = logging.getLogger(__name__)


class EventLogger:
    """事件日志. 1 行 1 条 JSON, 追加写."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._path.open("a", encoding="utf-8", buffering=1)

    def write(self, event: Event) -> None:
        try:
            self._fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
            self._fh.flush()
        except Exception as exc:  # noqa: BLE001
            _log.warning("event log write failed: %s", exc)

    def read_recent(self, n: int = 100) -> list[dict[str, Any]]:
        """读最近 n 条(尾部). 倒序返回."""
        if not self._path.exists():
            return []
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except Exception:  # noqa: BLE001
            return []
        out: list[dict] = []
        for line in reversed(lines):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(out) >= n:
                break
        return out

    def read_since(
        self, since: datetime, type_filter: EventType | None = None
    ) -> list[dict[str, Any]]:
        """读 since 之后的, 可选按类型过滤."""
        out: list[dict] = []
        if not self._path.exists():
            return out
        for line in self._path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts_str = rec.get("ts", "")
            try:
                ts = datetime.fromisoformat(ts_str)
            except ValueError:
                continue
            # 用 <= 而不是 <, 边界事件也算
            if ts < since:
                continue
            if type_filter and rec.get("type") != type_filter.value:
                continue
            out.append(rec)
        return out

    def read_after_index(
        self, after: int, type_filter: EventType | None = None
    ) -> list[dict[str, Any]]:
        """读第 after 条之后的所有事件(按文件行号). 测试用, 避免 ts 精度问题."""
        if not self._path.exists():
            return []
        out: list[dict] = []
        for i, line in enumerate(self._path.read_text(encoding="utf-8").splitlines()):
            if i <= after:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if type_filter and rec.get("type") != type_filter.value:
                continue
            out.append(rec)
        return out

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
