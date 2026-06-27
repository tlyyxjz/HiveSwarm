"""MemoryStore — 3 层记忆, 包装 SQLite (跟 stub.store_sqlite 配合).

3 层:
  short_term: 当前 session, 临时, 经常清
  working:    当前任务, 任务结束可清
  long_term:  跨 session, 长期保留

跟 Letta MemGPT 类似, 但简化版 (MVP).
"""
from __future__ import annotations

import json
import time
from enum import Enum
from typing import Any

from stub.store_sqlite import SQLiteStore


class MemoryTier(str, Enum):
    SHORT = "short"      # session 临时
    WORKING = "working"  # 当前任务
    LONG = "long"        # 长期


class MemoryStore:
    """3 层记忆. 用 SQLite 做底层, 按前缀分表."""

    PREFIX = {
        MemoryTier.SHORT: "short:",
        MemoryTier.WORKING: "work:",
        MemoryTier.LONG: "long:",
    }

    def __init__(self, backend: SQLiteStore) -> None:
        self._db = backend

    def put(self, tier: MemoryTier, key: str, value: Any) -> None:
        full_key = self.PREFIX[tier] + key
        payload = {
            "value": value,
            "tier": tier.value,
            "ts": time.time(),
        }
        self._db.put(full_key, payload)

    def get(self, tier: MemoryTier, key: str, default: Any = None) -> Any:
        full_key = self.PREFIX[tier] + key
        rec = self._db.get(full_key)
        if rec is None:
            return default
        return rec.get("value", default)

    def delete(self, tier: MemoryTier, key: str) -> None:
        full_key = self.PREFIX[tier] + key
        self._db.delete(full_key)

    def list(self, tier: MemoryTier, prefix: str = "") -> list[str]:
        """列某层的 keys (去掉 tier 前缀)."""
        full_prefix = self.PREFIX[tier] + prefix
        all_keys = self._db.list_keys(full_prefix)
        strip = len(self.PREFIX[tier])
        return [k[strip:] for k in all_keys]

    def clear(self, tier: MemoryTier) -> int:
        """清空某层, 返回删了几条."""
        prefix = self.PREFIX[tier]
        keys = self._db.list_keys(prefix)
        for k in keys:
            self._db.delete(k)
        return len(keys)

    def promote(self, tier_from: MemoryTier, tier_to: MemoryTier, key: str) -> None:
        """记忆升级: short → long, 工作记忆 → 长期."""
        val = self.get(tier_from, key)
        if val is not None:
            self.put(tier_to, key, val)
            self.delete(tier_from, key)
