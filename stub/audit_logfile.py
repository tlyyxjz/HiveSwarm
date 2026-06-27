"""LogFileAudit — 写本地 JSONL. append-only,失败不阻塞业务."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from core.audit import AuditLogger

_log = logging.getLogger(__name__)


class LogFileAudit(AuditLogger):
    """本地 JSONL 审计. 1 行 1 条记录."""

    def __init__(self, log_path: str | Path) -> None:
        self._path = Path(log_path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # append mode,buffering=1 = 行缓冲
        self._fh = self._path.open("a", encoding="utf-8", buffering=1)

    def log(
        self,
        actor: str,
        action: str,
        target: str = "",
        result: str = "ok",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            record = {
                "ts": datetime.now().isoformat(),
                "actor": actor,
                "action": action,
                "target": target,
                "result": result,
                "metadata": metadata or {},
            }
            self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:  # 审计失败降级日志,不能阻塞业务
            _log.warning("audit write failed: %s", exc)

    def query(
        self,
        actor: str | None = None,
        action: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if actor and rec.get("actor") != actor:
                continue
            if action and rec.get("action") != action:
                continue
            if since and datetime.fromisoformat(rec["ts"]) < since:
                continue
            out.append(rec)
            if len(out) >= limit:
                break
        return out

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
