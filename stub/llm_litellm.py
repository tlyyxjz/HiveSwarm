"""配置驱动 LLM 调度器入口 — 客户在 config/default.toml [[providers]] 配模型。

用法:
    from stub.llm_litellm import dispatch
    reply = dispatch(messages=[...], cfg=cfg)

路由逻辑:
    1. cfg.brain.providers 注册表 → active_provider → 协议适配器
    2. 配置驱动失败 → raise ConfigurationError (不静默 fallthrough)
    3. env_fallback 仅在 chat() 兼容别名中使用 (向后兼容)
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any

from stub.llm_providers import (
    _PROTOCOL_DISPATCH,
    resolve_ollama as _resolve_ollama_async,
)

if TYPE_CHECKING:
    from stub.config_loader import Config, ProviderCfg

_log = logging.getLogger(__name__)
_STUB = "hiveswarm-MVP-stub-reply"


class ConfigurationError(RuntimeError):
    """LLM 配置错误 (active_provider 找不到 / 适配器缺失)。"""


def _find_provider(name: str, providers: tuple) -> "ProviderCfg | None":
    """从注册表按 name 查 provider。找不到返回 None, 由 caller 决定如何处理。"""
    for p in providers:
        if p.name == name:
            return p
    return None


# ── 公开 API ──────────────────────────────────────────────────────────


def dispatch(
    messages: list[dict[str, str]],
    cfg: "Config | None" = None,
    provider: str = "",
    model: str = "",
    **kwargs: Any,
) -> str:
    """配置驱动 LLM 调用。配置驱动失败时 raise ConfigurationError, 不静默 fallthrough。

    Args:
        messages: 标准 chat messages
        cfg: Config 对象 (必传, 走配置驱动)
        provider: 指定 provider 名 (覆盖 cfg.brain.active_provider)
        model: 指定模型 (覆盖 provider.model)
    """
    if not cfg or not cfg.brain.providers:
        raise ConfigurationError("no providers configured; pass cfg with brain.providers")

    name = provider or cfg.brain.active_provider
    prov = _find_provider(name, cfg.brain.providers)
    if prov is None:
        raise ConfigurationError(
            f"active_provider '{name}' not found in providers registry"
        )

    handler = _PROTOCOL_DISPATCH.get(prov.type)
    if handler is None:
        raise ConfigurationError(
            f"unsupported provider type '{prov.type}' for '{prov.name}'"
        )

    _model = model or prov.model
    try:
        result = handler(prov, messages, model=_model, **kwargs)
        if asyncio.iscoroutine(result):
            # 检测是否在 event loop 里 — 是则让 caller 用 await dispatch_async
            try:
                asyncio.get_running_loop()
                raise RuntimeError(
                    "dispatch() cannot call async adapter from running event loop; "
                    "use 'await dispatch_async(...)' instead"
                )
            except RuntimeError as loop_exc:
                if "cannot call async adapter" in str(loop_exc):
                    raise
                # 无运行 loop, 用 asyncio.run
                return asyncio.run(result)
        return result
    except Exception as exc:
        _log.warning("%s '%s' failed: %s", prov.type, prov.name, exc, exc_info=True)
        raise


async def dispatch_async(
    messages: list[dict[str, str]],
    cfg: "Config | None" = None,
    provider: str = "",
    model: str = "",
    **kwargs: Any,
) -> str:
    """async 版 dispatch — 在 event loop 中调用, 处理 async 适配器 (如 _call_ollama)."""
    if not cfg or not cfg.brain.providers:
        raise ConfigurationError("no providers configured; pass cfg with brain.providers")

    name = provider or cfg.brain.active_provider
    prov = _find_provider(name, cfg.brain.providers)
    if prov is None:
        raise ConfigurationError(
            f"active_provider '{name}' not found in providers registry"
        )

    handler = _PROTOCOL_DISPATCH.get(prov.type)
    if handler is None:
        raise ConfigurationError(
            f"unsupported provider type '{prov.type}' for '{prov.name}'"
        )

    _model = model or prov.model
    try:
        result = handler(prov, messages, model=_model, **kwargs)
        if asyncio.iscoroutine(result):
            return await result
        return result
    except Exception as exc:
        _log.warning("%s '%s' failed: %s", prov.type, prov.name, exc, exc_info=True)
        raise


# ── 向后兼容别名 ──────────────────────────────────────────────────────


def chat(
    messages: list[dict[str, str]],
    model: str = "gpt-4o-mini",
    **kwargs: Any,
) -> str:
    """兼容旧代码 — 等价于 dispatch(), 无 cfg 时降级到 env_fallback。"""
    try:
        return _env_fallback(messages, model=model, **kwargs)
    except Exception as exc:
        _log.warning("chat env_fallback failed: %s", exc, exc_info=True)
        return f"{_STUB} (error: {exc})"


def resolve_ollama(cfg: "Config | None" = None) -> tuple[str, str] | None:
    """同步壳 — 包 async resolve_ollama。处理已有 event loop 的情况。"""
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            return asyncio.run(_resolve_ollama_async(cfg))
        # 已有 loop 在跑 — 不在这里再开, 返回 None 让 caller 决定
        return None
    except Exception:
        return None


def _resolve_ollama() -> tuple[str, str] | None:
    """兼容旧代码 — 等价于 resolve_ollama()。"""
    return resolve_ollama()


def _resolve_minimax() -> tuple[str, str, str] | None:
    """兼容旧代码。"""
    return None


def _env_fallback(messages: list[dict], model: str = "", **kwargs: Any) -> str:
    """环境变量回退 (向后兼容 — 老代码可能不传 cfg)."""
    import litellm
    from stub.llm_providers import _call_ollama as _ollama_handler

    key = os.getenv("MINIMAX_API_KEY", "")
    if key:
        base = os.getenv("MINIMAX_API_BASE", "https://api.minimax.chat/v1")
        mm_model = os.getenv("MINIMAX_MODEL", model or "minimax-m3-plus")
        resp = litellm.completion(
            model=f"openai/{mm_model}",
            messages=messages,
            api_key=key,
            api_base=base,
            **kwargs,
        )
        return resp.choices[0].message.content or ""

    ollama = resolve_ollama()
    if ollama:
        base, ollama_model = ollama
        from stub.config_loader import ProviderCfg

        prov = ProviderCfg(
            name="ollama-fallback", type="ollama",
            base_url=base, model=ollama_model, api_key="",
        )
        coro = _ollama_handler(prov, messages, **kwargs)
        if asyncio.iscoroutine(coro):
            return asyncio.run(coro)
        return coro

    if os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"):
        resp = litellm.completion(
            model=model or "gpt-4o-mini", messages=messages, **kwargs
        )
        return resp.choices[0].message.content or ""

    return _STUB