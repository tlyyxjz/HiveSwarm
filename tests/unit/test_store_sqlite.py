"""SQLiteStore 单测 — 持久化核心, 数据丢失风险."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from stub.store_sqlite import SQLiteStore


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    """每个测试独立 sqlite 文件, 自动清理."""
    return SQLiteStore(tmp_path / "test.db")


# ── 基本 CRUD ────────────────────────────────────────────────

class TestBasicCRUD:
    def test_put_get_simple_value(self, store: SQLiteStore) -> None:
        store.put("k1", "hello")
        assert store.get("k1") == "hello"

    def test_put_get_dict(self, store: SQLiteStore) -> None:
        data = {"name": "alice", "age": 30, "tags": ["a", "b"]}
        store.put("k1", data)
        assert store.get("k1") == data

    def test_put_get_list(self, store: SQLiteStore) -> None:
        store.put("k1", [1, 2, 3, 4])
        assert store.get("k1") == [1, 2, 3, 4]

    def test_get_missing_returns_default(self, store: SQLiteStore) -> None:
        assert store.get("nope") is None
        assert store.get("nope", "fallback") == "fallback"

    def test_put_overwrites_existing(self, store: SQLiteStore) -> None:
        store.put("k1", "v1")
        store.put("k1", "v2")
        assert store.get("k1") == "v2"

    def test_delete_removes_key(self, store: SQLiteStore) -> None:
        store.put("k1", "v")
        store.delete("k1")
        assert store.get("k1") is None

    def test_delete_missing_no_error(self, store: SQLiteStore) -> None:
        store.delete("nope")  # 不报错


# ── 列表 / 前缀 ──────────────────────────────────────────────

class TestListKeys:
    def test_list_keys_all(self, store: SQLiteStore) -> None:
        store.put("a", 1)
        store.put("b", 2)
        store.put("c", 3)
        assert sorted(store.list_keys()) == ["a", "b", "c"]

    def test_list_keys_prefix(self, store: SQLiteStore) -> None:
        store.put("task:1", "x")
        store.put("task:2", "y")
        store.put("plan:1", "z")
        assert sorted(store.list_keys("task:")) == ["task:1", "task:2"]
        assert store.list_keys("plan:") == ["plan:1"]
        assert store.list_keys("nope:") == []

    def test_list_keys_empty(self, store: SQLiteStore) -> None:
        assert store.list_keys() == []


# ── Unicode ──────────────────────────────────────────────────

class TestUnicode:
    def test_chinese(self, store: SQLiteStore) -> None:
        store.put("msg", "你好世界 🐝")
        assert store.get("msg") == "你好世界 🐝"

    def test_chinese_dict(self, store: SQLiteStore) -> None:
        data = {"用户": "张三", "标签": ["中文", "测试"]}
        store.put("cn", data)
        assert store.get("cn") == data


# ── 损坏数据降级 ────────────────────────────────────────────

class TestCorruptionResilience:
    def test_corrupted_json_returns_default(self, tmp_path: Path) -> None:
        """手写损坏 JSON 进表 → get 返回 default 不抛."""
        import sqlite3
        db = tmp_path / "corrupt.db"
        store = SQLiteStore(db)
        # 直接塞非 JSON
        with sqlite3.connect(str(db)) as c:
            c.execute(
                "INSERT INTO memory(key, value, ts) VALUES(?, ?, ?)",
                ("bad", "{not valid json", 0.0),
            )
        assert store.get("bad", "fallback") == "fallback"


# ── 并发 ─────────────────────────────────────────────────────

class TestConcurrency:
    def test_concurrent_puts_no_error(self, tmp_path: Path) -> None:
        """多线程同时 put 不同 key → 不报错, 所有 key 都能读到."""
        store = SQLiteStore(tmp_path / "concurrent.db")
        errors: list[Exception] = []

        def worker(idx: int) -> None:
            try:
                for j in range(5):
                    store.put(f"key-{idx}-{j}", j)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        # 4 workers × 5 keys = 20
        assert len(store.list_keys()) == 20

    def test_concurrent_same_key_overwrites(self, tmp_path: Path) -> None:
        """多线程 put 同一 key → 不报错, 最终值是某个线程写的."""
        store = SQLiteStore(tmp_path / "samekey.db")
        errors: list[Exception] = []

        def worker(idx: int) -> None:
            try:
                for _ in range(10):
                    store.put("shared", idx)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        final = store.get("shared")
        assert final in range(4)


# ── 文件路径处理 ────────────────────────────────────────────

class TestPathHandling:
    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c" / "test.db"
        store = SQLiteStore(nested)
        store.put("k", "v")
        assert nested.exists()
        assert store.get("k") == "v"

    def test_expanduser_tilde(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """~/path 会被 expanduser (Windows 走 USERPROFILE)."""
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))  # 兼容 POSIX
        store = SQLiteStore("~/test_expand.db")
        store.put("k", "v")
        assert store.get("k") == "v"
        assert (tmp_path / "test_expand.db").exists()