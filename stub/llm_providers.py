"""LLM 协议适配器 — Ollama / Anthropic / OpenAI 三协议统一签名。

公开接口:
    _no_proxy_for_localhost() — contextmanager, 临时 bypass 系统代理访问 localhost
    _call_ollama(provider, messages, **kwargs) -> str  (async)
    _call_anthropic(provider, messages, **kwargs) -> str
    _call_openai(provider, messages, **kwargs) -> str
    _PROTOCOL_DISPATCH: dict[str, Callable]
    resolve_ollama(cfg) -> tuple[str, str] | None  (async)

所有适配器签名一致 (provider, messages, **kwargs) -> str。
import litellm 仅在顶部一次 (按"DRY"关 1 要求)。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import httpx
import litellm  # 顶部唯一 import (按"DRY"关 1)

if TYPE_CHECKING:
    from stub.config_loader import Config, ProviderCfg

_log = logging.getLogger(__name__)


# ── NO_PROXY 唯一实现 (其他文件 import) ───────────────────────────────


@contextmanager
def _no_proxy_for_localhost():
    """临时 bypass 系统代理访问 localhost/127.0.0.1。"""
    saved = os.environ.pop("NO_PROXY", None)
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    try:
        yield
    finally:
        if saved is not None:
            os.environ["NO_PROXY"] = saved
        else:
            os.environ.pop("NO_PROXY", None)


# ── 三协议适配器 (签名一致) ─────────────────────────────────────────


async def _call_ollama(provider: "ProviderCfg", messages: list[dict], **kwargs: Any) -> str:
    """Ollama 本地模型 — /api/chat (非 Anthropic 兼容)。

    用 httpx.AsyncClient 异步发请求, 禁 urllib.request 同步阻塞。
    """
    ollama_msgs: list[dict] = []
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, list):
            text = " ".join(
                b.get("text", "") for b in content if b.get("type") == "text"
            )
        else:
            text = str(content)
        ollama_msgs.append({"role": m["role"], "content": text})

    body = {
        "model": provider.model,
        "messages": ollama_msgs,
        "stream": False,
        "options": {"num_predict": kwargs.get("max_tokens", 512)},
    }
    with _no_proxy_for_localhost():
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{provider.base_url}/api/chat",
                json=body,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content") or ""


def _call_anthropic(provider: "ProviderCfg", messages: list[dict], **kwargs: Any) -> str:
    """Anthropic Messages API 兼容端点 (DeepSeek / MiniMax / Claude)。"""
    key = provider.resolve_key()
    kwargs.pop("model", None)
    resp = litellm.completion(
        model=f"anthropic/{provider.model}",
        messages=messages,
        api_key=key,
        api_base=provider.base_url,
        **kwargs,
    )
    return resp.choices[0].message.content or ""


def _call_openai(provider: "ProviderCfg", messages: list[dict], **kwargs: Any) -> str:
    """OpenAI Chat Completions API。"""
    key = provider.resolve_key()
    kwargs.pop("model", None)
    resp = litellm.completion(
        model=provider.model,
        messages=messages,
        api_key=key,
        api_base=provider.base_url,
        **kwargs,
    )
    return resp.choices[0].message.content or ""


_PROTOCOL_DISPATCH = {
    "ollama": _call_ollama,
    "anthropic": _call_anthropic,
    "openai": _call_openai,
}


# ── Ollama 健康探测 (async) ─────────────────────────────────────────


async def resolve_ollama(cfg: "Config | None" = None) -> tuple[str, str] | None:
    """检测 Ollama 是否可用 → (base_url, model)。timeout=5s 防冷启动漏检。"""
    # 1. 配置驱动
    if cfg and cfg.brain.providers:
        for p in cfg.brain.providers:
            if p.type == "ollama":
                if await _ping_ollama(p.base_url):
                    return p.base_url, p.model
    # 2. 环境变量回退
    base = os.getenv("OLLAMA_API_BASE", "http://127.0.0.1:11434")
    model = os.getenv("OLLAMA_MODEL", "qwen3:8b")
    if await _ping_ollama(base):
        return base, model
    return None


async def _ping_ollama(base_url: str) -> bool:
    """真测 Ollama /api/tags 是否可达 (timeout=5s)。"""
    try:
        with _no_proxy_for_localhost():
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{base_url}/api/tags")
                return r.is_success
    except Exception as exc:
        _log.debug("ollama ping %s failed: %s", base_url, exc)
        return False