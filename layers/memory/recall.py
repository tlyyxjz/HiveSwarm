"""Recall — 回忆策略.

按 key / 按 prefix / 按时间倒序, 选最近 N 条.
语义搜索通过 bge-m3 嵌入做余弦相似度匹配.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any

import httpx

from layers.memory.store import MemoryStore, MemoryTier
from stub.llm_providers import _no_proxy_for_localhost

_log = logging.getLogger(__name__)


def recall_by_key(store: MemoryStore, tier: MemoryTier, key: str) -> Any:
    """最简单: 按 key 拿."""
    return store.get(tier, key)


def recall_by_prefix(
    store: MemoryStore, tier: MemoryTier, prefix: str = "", limit: int = 50
) -> list[dict[str, Any]]:
    """按 prefix 列, 返回 [{key, value, ts}, ...], 按 ts 倒序."""
    keys = store.list(tier, prefix)
    out: list[dict] = []
    for k in keys[:limit]:
        full_key = store.PREFIX[tier] + k
        rec = store._db.get(full_key)
        if rec is None:
            continue
        out.append({"key": k, "value": rec.get("value"), "ts": rec.get("ts", 0)})
    out.sort(key=lambda r: r["ts"], reverse=True)
    return out


def recall_recent(
    store: MemoryStore,
    tiers: tuple[MemoryTier, ...] = (MemoryTier.WORKING, MemoryTier.LONG),
    limit: int = 20,
) -> list[dict[str, Any]]:
    """跨层取最近 N 条, 按 ts 倒序."""
    all_recs: list[dict] = []
    for t in tiers:
        all_recs.extend(recall_by_prefix(store, t, "", limit=limit * 2))
    all_recs.sort(key=lambda r: r["ts"], reverse=True)
    return all_recs[:limit]


# ── 语义搜索 ──────────────────────────────────────────────────────────────


async def _ollama_embed(
    texts: list[str], base: str, model: str
) -> list[list[float]] | None:
    """调用 Ollama 批量嵌入。一组 text → 一组向量。失败返回 None (带 exc_info)。"""
    try:
        body = {"model": model, "input": texts}
        with _no_proxy_for_localhost():
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{base}/api/embed",
                    json=body,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                return resp.json().get("embeddings")
    except Exception as exc:
        _log.warning("ollama embed failed (model=%s, n=%d): %s", model, len(texts), exc, exc_info=True)
        return None


async def _embed_in_batches(
    texts: list[str],
    base: str,
    model: str,
    batch_size: int,
) -> list[list[float]]:
    """分批嵌入 — 超 batch_size 自动切批, 拼接结果。全部失败抛空 list。"""
    if batch_size <= 0:
        batch_size = 20
    all_vecs: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i : i + batch_size]
        vecs = await _ollama_embed(chunk, base, model)
        if vecs is None:
            return []
        all_vecs.extend(vecs)
    return all_vecs


def _filter_by_window(
    records: list[dict], window_days: int, now: float | None = None
) -> list[dict]:
    """按时间窗口过滤。window_days <= 0 不过滤。"""
    if window_days <= 0:
        return records
    cutoff = (now or time.time()) - window_days * 86400
    return [r for r in records if r.get("ts", 0) >= cutoff]


async def recall_semantic(
    store: MemoryStore,
    query: str,
    tier: MemoryTier = MemoryTier.LONG,
    limit: int = 5,
    cfg: "object | None" = None,
    ollama_base: str = "http://127.0.0.1:11434",
) -> list[dict[str, Any]]:
    """语义搜索 — 用配置的嵌入模型计算余弦相似度匹配历史记录。

    配置驱动 (cfg.memory.embedding_model / batch_size / window_days)。
    Ollama 不可达或嵌入失败 → 返回 [], 不抛异常 (caller 可降级)。

    Args:
        store: MemoryStore 实例
        query: 搜索查询
        tier: 搜索哪个记忆层
        limit: 返回结果数
        cfg: Config 对象 (含 memory.embedding_model / batch_size / window_days)
        ollama_base: Ollama API 地址 (cfg 缺省时使用)
    """
    # 1. 读配置 (缺 cfg 走默认)
    embedding_model = "bge-m3:latest"
    batch_size = 20
    window_days = 30
    if cfg is not None and getattr(cfg, "memory", None):
        embedding_model = getattr(cfg.memory, "embedding_model", embedding_model)
        batch_size = int(getattr(cfg.memory, "batch_size", batch_size))
        window_days = int(getattr(cfg.memory, "window_days", window_days))

    records = recall_by_prefix(store, tier, "", limit=200)
    if not records:
        return []
    records = _filter_by_window(records, window_days)
    if not records:
        return []

    texts = [query]
    text_indices: list[int] = []
    for i, rec in enumerate(records):
        val = rec.get("value", "")
        if isinstance(val, str) and val:
            texts.append(val[:2000])
            text_indices.append(i)
        else:
            rec["score"] = 0.0

    all_vecs = await _embed_in_batches(texts, ollama_base, embedding_model, batch_size)
    if not all_vecs or len(all_vecs) != len(texts):
        return []

    query_vec = all_vecs[0]

    def _dot(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))

    def _norm(a: list[float]) -> float:
        return math.sqrt(sum(x * x for x in a))

    q_norm = _norm(query_vec) + 1e-8
    for j, rec_idx in enumerate(text_indices):
        rec_vec = all_vecs[j + 1]
        sim = _dot(query_vec, rec_vec) / (q_norm * _norm(rec_vec) + 1e-8)
        records[rec_idx]["score"] = sim

    records.sort(key=lambda r: r.get("score", 0), reverse=True)
    return records[:limit]