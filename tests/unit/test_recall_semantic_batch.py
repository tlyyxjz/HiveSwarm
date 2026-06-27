"""recall_semantic 重构测试 — 5 条单元测试.

覆盖:
    1. batch_size 参数生效 (分批嵌入)
    2. 嵌入模型从 cfg.memory.embedding_model 读取
    3. 时间窗口过滤生效 (默认 30 天)
    4. Ollama 不可达返回 [] 不抛异常
    5. 嵌入数量 mismatch → 返回 []
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from layers.memory.recall import (
    _embed_in_batches,
    _filter_by_window,
    _ollama_embed,
    recall_semantic,
)
from layers.memory.store import MemoryStore, MemoryTier
from stub.store_sqlite import SQLiteStore


# ── helpers ────────────────────────────────────────────────────────


def _make_store_with_records(tmp_path, records: list[tuple[str, str, float]]):
    """构造 store + records (key, value, ts)."""
    db = SQLiteStore(tmp_path / "mem.db")
    store = MemoryStore(db)
    for key, val, ts in records:
        full_key = MemoryStore.PREFIX[MemoryTier.LONG] + key
        db.put(full_key, {"value": val, "tier": "long", "ts": ts})
    return store


class _FakeCfg:
    """模拟 cfg.memory 字段."""

    def __init__(self, embedding_model="bge-m3:latest", batch_size=20, window_days=30):
        self.memory = MagicMock()
        self.memory.embedding_model = embedding_model
        self.memory.batch_size = batch_size
        self.memory.window_days = window_days


# ── 1. batch_size 分批嵌入 ──────────────────────────────────────────


class TestBatchSize:
    def test_batch_size_triggers_chunking(self):
        """25 条文本 + batch_size=10 → _ollama_embed 调用 3 次 (10+10+5)."""
        texts = [f"text-{i}" for i in range(25)]

        async def fake_embed(chunk, base, model):
            # 每个 chunk 返回等长度的零向量
            return [[0.0] * 4 for _ in chunk]

        with patch("layers.memory.recall._ollama_embed", side_effect=fake_embed) as mock_embed:
            result = asyncio.run(_embed_in_batches(texts, "http://x", "m", 10))

        assert len(result) == 25, "should concatenate 3 batches into 25 vectors"
        assert mock_embed.call_count == 3, f"expected 3 batches, got {mock_embed.call_count}"
        # 验证 chunk 大小: 10, 10, 5
        sizes = [len(call.args[0]) for call in mock_embed.call_args_list]
        assert sizes == [10, 10, 5], f"chunk sizes wrong: {sizes}"


# ── 2. 嵌入模型从 cfg 读 ──────────────────────────────────────────


class TestEmbeddingModelFromCfg:
    def test_recall_uses_cfg_embedding_model(self, tmp_path):
        """recall_semantic 必须把 cfg.memory.embedding_model 传给 _ollama_embed."""
        now = time.time()
        store = _make_store_with_records(tmp_path, [
            ("a", "alpha content", now),
            ("b", "beta content", now),
        ])
        cfg = _FakeCfg(embedding_model="custom-embed-model", batch_size=10)

        async def fake_embed(texts, base, model):
            # 返回每个文本一个 4 维零向量
            return [[0.0] * 4 for _ in texts]

        with patch("layers.memory.recall._ollama_embed", side_effect=fake_embed) as mock_embed:
            asyncio.run(recall_semantic(store, "query", cfg=cfg))

        # 检查传给 _ollama_embed 的 model 参数
        first_call = mock_embed.call_args_list[0]
        assert first_call.kwargs.get("model") == "custom-embed-model" or \
               (len(first_call.args) >= 3 and first_call.args[2] == "custom-embed-model"), \
            f"_ollama_embed should receive 'custom-embed-model', got {first_call}"


# ── 3. 时间窗口过滤生效 ──────────────────────────────────────────


class TestWindowFilter:
    def test_old_records_excluded(self, tmp_path):
        """100 天前的记录被默认 30 天窗口过滤掉."""
        now = time.time()
        store = _make_store_with_records(tmp_path, [
            ("fresh", "new content", now),
            ("old", "old content", now - 100 * 86400),  # 100 天前
        ])
        cfg = _FakeCfg(window_days=30)

        async def fake_embed(texts, base, model):
            return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

        with patch("layers.memory.recall._ollama_embed", side_effect=fake_embed):
            result = asyncio.run(recall_semantic(store, "query", cfg=cfg))

        keys = [r["key"] for r in result]
        assert "fresh" in keys
        assert "old" not in keys, f"100-day-old record should be filtered out: {keys}"

    def test_window_days_zero_no_filter(self):
        """window_days=0 → 不过滤."""
        records = [
            {"key": "a", "value": "x", "ts": 0},
            {"key": "b", "value": "y", "ts": time.time()},
        ]
        out = _filter_by_window(records, window_days=0)
        assert len(out) == 2


# ── 4. Ollama 不可达返回 [] ──────────────────────────────────────


class TestOllamaUnreachable:
    def test_returns_empty_on_failure(self, tmp_path):
        """_ollama_embed 失败 → recall_semantic 返回 [], 不抛异常."""
        now = time.time()
        store = _make_store_with_records(tmp_path, [
            ("a", "alpha", now),
            ("b", "beta", now),
        ])
        cfg = _FakeCfg()

        async def boom(texts, base, model):
            return None

        with patch("layers.memory.recall._ollama_embed", side_effect=boom):
            # 不应抛异常
            result = asyncio.run(recall_semantic(store, "query", cfg=cfg))
        assert result == []


# ── 5. 嵌入数量 mismatch → [] ─────────────────────────────────────


class TestEmbeddingCountMismatch:
    def test_mismatch_returns_empty(self, tmp_path):
        """all_vecs 长度 != texts 长度 → 返回 []."""
        now = time.time()
        store = _make_store_with_records(tmp_path, [
            ("a", "alpha", now),
            ("b", "beta", now),
        ])
        cfg = _FakeCfg(batch_size=10)

        async def wrong_count(texts, base, model):
            # 只返回 N-1 个向量
            return [[0.0] * 4 for _ in range(len(texts) - 1)]

        with patch("layers.memory.recall._ollama_embed", side_effect=wrong_count):
            result = asyncio.run(recall_semantic(store, "query", cfg=cfg))
        assert result == []