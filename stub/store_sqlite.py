"""SQLiteStore — MVP 记忆存储. 换 Qdrant/Redis 时改 1 行配置."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class SQLiteStore:
    """轻量记忆存储. 同步 API 够 MVP 用,Thread-safe by Lock."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS memory (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    ts    REAL NOT NULL
                )
                """
            )

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            c = sqlite3.connect(str(self._path))
            try:
                yield c
                c.commit()
            finally:
                c.close()

    def put(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO memory(key, value, ts) VALUES(?,?,?)",
                (key, payload, time.time()),
            )

    def get(self, key: str, default: Any = None) -> Any:
        with self._conn() as c:
            row = c.execute("SELECT value FROM memory WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return default

    def delete(self, key: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM memory WHERE key=?", (key,))

    def list_keys(self, prefix: str = "") -> list[str]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT key FROM memory WHERE key LIKE ?", (f"{prefix}%",)
            ).fetchall()
        return [r[0] for r in rows]
