"""Memory 层单元测试."""
from __future__ import annotations

import time

import pytest

from layers.memory.recall import recall_by_key, recall_by_prefix, recall_recent
from layers.memory.store import MemoryStore, MemoryTier
from stub.store_sqlite import SQLiteStore


@pytest.fixture
def store(tmp_path):
    db = SQLiteStore(tmp_path / "mem.db")
    return MemoryStore(db)


# ── 基本 put/get ────────────────────────────────────────────────────

class TestPutGet:
    def test_put_get_short(self, store):
        store.put(MemoryTier.SHORT, "k1", "v1")
        assert store.get(MemoryTier.SHORT, "k1") == "v1"

    def test_put_get_working(self, store):
        store.put(MemoryTier.WORKING, "k1", {"a": 1})
        assert store.get(MemoryTier.WORKING, "k1") == {"a": 1}

    def test_put_get_long(self, store):
        store.put(MemoryTier.LONG, "profile", {"name": "user"})
        assert store.get(MemoryTier.LONG, "profile") == {"name": "user"}

    def test_get_default(self, store):
        assert store.get(MemoryTier.SHORT, "nope", default="d") == "d"

    def test_keys_isolated_by_tier(self, store):
        """同名 key 在不同层不冲突."""
        store.put(MemoryTier.SHORT, "k", "short_val")
        store.put(MemoryTier.LONG, "k", "long_val")
        assert store.get(MemoryTier.SHORT, "k") == "short_val"
        assert store.get(MemoryTier.LONG, "k") == "long_val"


# ── list / clear ────────────────────────────────────────────────────

class TestListClear:
    def test_list_with_prefix(self, store):
        store.put(MemoryTier.LONG, "user:1", "a")
        store.put(MemoryTier.LONG, "user:2", "b")
        store.put(MemoryTier.LONG, "task:1", "c")
        assert set(store.list(MemoryTier.LONG, "user:")) == {"user:1", "user:2"}

    def test_list_all_in_tier(self, store):
        store.put(MemoryTier.SHORT, "a", 1)
        store.put(MemoryTier.SHORT, "b", 2)
        assert set(store.list(MemoryTier.SHORT)) == {"a", "b"}

    def test_clear_tier(self, store):
        store.put(MemoryTier.SHORT, "a", 1)
        store.put(MemoryTier.SHORT, "b", 2)
        store.put(MemoryTier.LONG, "c", 3)
        n = store.clear(MemoryTier.SHORT)
        assert n == 2
        assert store.list(MemoryTier.SHORT) == []
        # long 不动
        assert store.list(MemoryTier.LONG) == ["c"]


# ── promote ────────────────────────────────────────────────────────

class TestPromote:
    def test_promote_short_to_long(self, store):
        store.put(MemoryTier.SHORT, "k", "v")
        store.promote(MemoryTier.SHORT, MemoryTier.LONG, "k")
        assert store.get(MemoryTier.SHORT, "k") is None
        assert store.get(MemoryTier.LONG, "k") == "v"

    def test_promote_missing_does_nothing(self, store):
        store.promote(MemoryTier.SHORT, MemoryTier.LONG, "nope")
        # 不爆, 没效果
        assert store.get(MemoryTier.LONG, "nope") is None


# ── recall ─────────────────────────────────────────────────────────

class TestRecall:
    def test_recall_by_key(self, store):
        store.put(MemoryTier.LONG, "x", 42)
        assert recall_by_key(store, MemoryTier.LONG, "x") == 42

    def test_recall_by_prefix_orders_by_ts(self, store):
        store.put(MemoryTier.LONG, "a", "first")
        time.sleep(0.02)
        store.put(MemoryTier.LONG, "b", "second")
        time.sleep(0.02)
        store.put(MemoryTier.LONG, "c", "third")
        recs = recall_by_prefix(store, MemoryTier.LONG, "", limit=10)
        # 倒序: c, b, a
        assert [r["key"] for r in recs] == ["c", "b", "a"]

    def test_recall_recent_cross_tier(self, store):
        store.put(MemoryTier.SHORT, "a", "s1")
        time.sleep(0.02)
        store.put(MemoryTier.WORKING, "b", "w1")
        time.sleep(0.02)
        store.put(MemoryTier.LONG, "c", "l1")
        recs = recall_recent(store, (MemoryTier.SHORT, MemoryTier.WORKING, MemoryTier.LONG), limit=10)
        # 倒序跨层: c, b, a
        keys = [r["key"] for r in recs]
        assert keys[0] == "c"
        assert keys[-1] == "a"
