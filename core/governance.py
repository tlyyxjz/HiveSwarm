"""Governance — 数据治理 ABC.

职责:数据保留 / 脱敏 / 合规. 公司里 PII 数据 30 天自动删,GPT 输出要
脱敏. MVP 永久保留(本地),公司里接公司 DLP.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DataRetention(ABC):
    """数据保留策略."""

    @abstractmethod
    def should_retain(self, record: dict[str, Any], age_days: int) -> bool:
        """这条数据是否还能保留."""

    @abstractmethod
    def scrub_pii(self, text: str) -> str:
        """脱敏. 把邮箱/手机号/身份证号 → [REDACTED]."""
