"""AuditLogger — 审计日志 ABC.

职责:把"谁在什么时间做了什么任务/决策"写入不可篡改存储. 公司用必备
(SOC2/HIPAA/等保). MVP 写本地 JSONL,公司里换 Kafka / S3 / 链式哈希.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class AuditLogger(ABC):
    """审计日志. append-only,失败不能影响主流程(降级本地缓存)."""

    @abstractmethod
    def log(
        self,
        actor: str,
        action: str,
        target: str = "",
        result: str = "ok",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """记一条审计. metadata 自由扩展(SkillManifest / 决策依据 等)."""

    @abstractmethod
    def query(
        self,
        actor: str | None = None,
        action: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """查审计(给 dashboard / 合规用)."""
