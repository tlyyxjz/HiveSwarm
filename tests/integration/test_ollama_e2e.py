"""Ollama 端到端集成测试 — 3 条.

运行条件: Ollama 在 http://127.0.0.1:11434 可用, 且 bge-m3 / qwen3:8b 模型已 pull.
否则 pytest.skip.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx
import pytest

from stub.config_loader import BrainCfg, Config, MemoryCfg, ProviderCfg, load_config
from stub.llm_litellm import dispatch


OLLAMA_BASE = "http://127.0.0.1:11434"


def _ollama_alive() -> bool:
    """检查 Ollama /api/tags 可达 + 返回 200."""
    try:
        r = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=5.0)
        return r.status_code == 200 and "models" in r.json()
    except Exception:
        return False


def _has_model(name: str) -> bool:
    """检查指定模型已 pull."""
    try:
        r = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=5.0)
        if r.status_code != 200:
            return False
        models = [m.get("name", "") for m in r.json().get("models", [])]
        return any(name in m for m in models)
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _ollama_alive(),
    reason="Ollama not reachable at " + OLLAMA_BASE,
)


# ── 1. 实际 Ollama 健康 ──────────────────────────────────────────


class TestOllamaHealth:
    def test_real_ollama_health(self):
        """Ollama 真健康 — /api/tags 返回 200 + models 列表."""
        r = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=5.0)
        assert r.status_code == 200
        data = r.json()
        assert "models" in data
        assert isinstance(data["models"], list)
        # 至少应有一个模型 (or skip if empty)
        if not data["models"]:
            pytest.skip("Ollama has no models pulled")


# ── 2. dispatch 真发请求拿回字符串 ─────────────────────────────


class TestDispatchRealCall:
    def test_dispatch_ollama_local_real_call(self):
        """dispatch(cfg with active_provider=ollama-local) 真发请求拿回字符串."""
        if not _has_model("qwen3:8b"):
            pytest.skip("qwen3:8b not pulled")

        cfg = load_config()
        result = dispatch(
            [{"role": "user", "content": "Reply with just the word: PONG"}],
            cfg=cfg,
        )
        assert isinstance(result, str)
        assert len(result) > 0, "Ollama returned empty string"
        # 真模型不一定答 PONG, 但不应是 stub 字符串
        assert "hiveswarm-MVP-stub-reply" not in result, \
            f"got stub fallback instead of real response: {result!r}"


# ── 3. recall_semantic 真用 bge-m3 算相似度 ─────────────────────


class TestRecallSemanticReal:
    def test_recall_semantic_real_embedding(self, tmp_path):
        """recall_semantic 真用 bge-m3 嵌入算相似度."""
        if not _has_model("bge-m3"):
            pytest.skip("bge-m3 not pulled")

        from layers.memory.recall import recall_semantic
        from layers.memory.store import MemoryStore
        from stub.store_sqlite import SQLiteStore

        db = SQLiteStore(tmp_path / "mem.db")
        store = MemoryStore(db)
        now = time.time()
        # 5 条 mock 记忆
        records = [
            ("k1", "猫喜欢吃鱼", now),
            ("k2", "狗喜欢啃骨头", now),
            ("k3", "Python 是编程语言", now),
            ("k4", "机器学习中嵌入很重要", now),
            ("k5", "Ollama 本地跑大模型", now),
        ]
        for k, v, ts in records:
            full_key = MemoryStore.PREFIX[MemoryStore.MemoryTier.LONG] + k
            db.put(full_key, {"value": v, "tier": "long", "ts": ts})

        cfg = load_config()
        # 查询: "猫和鱼的关系" — 应该和 k1 (猫吃鱼) 相似度最高
        result = asyncio.run(recall_semantic(store, "猫和鱼的关系", cfg=cfg))

        assert isinstance(result, list)
        assert len(result) > 0, "should return at least one result"
        # 所有结果应有 score 字段
        assert all("score" in r for r in result)
        # 排序应按 score 降序
        scores = [r["score"] for r in result]
        assert scores == sorted(scores, reverse=True), \
            f"results not sorted by score desc: {scores}"
        # bge-m3 对中文短文本的相似度应 > 0
        assert max(scores) > 0.0, f"max score should be > 0: {scores}"