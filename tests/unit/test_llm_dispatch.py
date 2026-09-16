"""覆盖率补测 (T3.3): llm_litellm dispatch / llm_providers 适配器的行为测试.

不发真实网络请求: 靠 ConfigurationError 路径 / monkeypatch 适配器 / ping 不可达端口.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from stub.config_loader import BrainCfg, Config, MonitorCfg, ProviderCfg, RepairCfg
from stub.llm_litellm import ConfigurationError, _find_provider, chat, dispatch, dispatch_async, resolve_ollama
from stub.llm_providers import (
    _PROTOCOL_DISPATCH,
    _no_proxy_for_localhost,
    _ping_ollama,
)


def _cfg(active: str = "main", providers=(ProviderCfg(
    name="main", type="openai", base_url="http://127.0.0.1:9", model="m1", api_key="k"
),)) -> Config:
    return Config(
        brain=BrainCfg(llm_provider="", llm_model="", planner_system_prompt="",
                       active_provider=active, providers=tuple(providers)),
        repair=RepairCfg(strategy="", max_retries=1, retry_delay_s=0.0, pause_threshold=3),
        monitor=MonitorCfg(bus="", dashboard="", dashboard_port=0, log_path="", log_max_size_mb=1),
        memory=None, auth=None, audit=None, billing=None, tenant=None,
        recovery=None, telemetry=None, governance=None, gateway=None, skills=None,
    )


class TestNoProxy:
    def test_bypass_and_restore(self, monkeypatch):
        monkeypatch.setenv("NO_PROXY", "custom")
        with _no_proxy_for_localhost():
            import os
            assert "127.0.0.1" in os.environ["NO_PROXY"]
        import os
        assert os.environ["NO_PROXY"] == "custom"  # 恢复原值

    def test_restore_when_unset_before(self, monkeypatch):
        monkeypatch.delenv("NO_PROXY", raising=False)
        with _no_proxy_for_localhost():
            import os
            assert "localhost" in os.environ["NO_PROXY"]
        import os
        assert "NO_PROXY" not in os.environ  # 原来没有 → 用后移除


class TestProtocolDispatch:
    def test_anthropic_and_openai_registered(self):
        assert set(_PROTOCOL_DISPATCH) >= {"anthropic", "openai"}
        # ollama 默认不注册 (公司版禁用), 只能动态加入
        assert "ollama" not in _PROTOCOL_DISPATCH

    def test_adapter_signatures_uniform(self):
        import inspect
        for fn in _PROTOCOL_DISPATCH.values():
            sig = inspect.signature(fn)
            assert list(sig.parameters)[:2] == ["provider", "messages"]


class TestPingOllama:
    @pytest.mark.asyncio
    async def test_ping_unreachable_is_false(self):
        assert await _ping_ollama("http://127.0.0.1:9") is False  # 不可达端口

    @pytest.mark.asyncio
    async def test_resolve_ollama_none_when_down(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_API_BASE", "http://127.0.0.1:9")
        from stub.llm_providers import resolve_ollama as ro
        assert await ro(None) is None


class TestDispatch:
    def test_no_cfg_raises(self):
        with pytest.raises(ConfigurationError, match="no providers"):
            dispatch([{"role": "user", "content": "x"}], cfg=None)

    def test_unknown_active_provider_raises(self):
        with pytest.raises(ConfigurationError, match="not found"):
            dispatch([{"role": "user", "content": "x"}], cfg=_cfg(active="ghost"))

    def test_unsupported_type_raises(self):
        cfg = _cfg(providers=(ProviderCfg(
            name="main", type="carrier_pigeon", base_url="x", model="m", api_key="k"),))
        with pytest.raises(ConfigurationError, match="unsupported provider type"):
            dispatch([{"role": "user", "content": "x"}], cfg=cfg)

    @pytest.mark.asyncio
    async def test_async_adapter_in_loop_raises_hint(self):
        """在运行中的 event loop 里调同步 dispatch 必须提示用 dispatch_async."""
        from stub import llm_providers

        async def fake_async(prov, messages, **kw):
            return "hi"

        llm_providers._PROTOCOL_DISPATCH["fake_async"] = fake_async
        try:
            cfg = _cfg(providers=(ProviderCfg(
                name="main", type="fake_async", base_url="x", model="m", api_key="k"),))
            with pytest.raises(RuntimeError, match="dispatch_async"):
                dispatch([{"role": "user", "content": "x"}], cfg=cfg)
        finally:
            llm_providers._PROTOCOL_DISPATCH.pop("fake_async", None)

    def test_async_adapter_outside_loop_runs_via_asyncio_run(self):
        """同步上下文里 async 适配器走 asyncio.run, 正常返回 (另一条合法路径)."""
        from stub import llm_providers

        async def fake_async(prov, messages, **kw):
            return "hi-async"

        llm_providers._PROTOCOL_DISPATCH["fake_async2"] = fake_async
        try:
            cfg = _cfg(providers=(ProviderCfg(
                name="main", type="fake_async2", base_url="x", model="m", api_key="k"),))
            assert dispatch([{"role": "user", "content": "x"}], cfg=cfg) == "hi-async"
        finally:
            llm_providers._PROTOCOL_DISPATCH.pop("fake_async2", None)

    @pytest.mark.asyncio
    async def test_dispatch_async_with_sync_adapter(self, monkeypatch):
        from stub import llm_providers

        monkeypatch.setitem(llm_providers._PROTOCOL_DISPATCH, "fake_sync",
                            lambda prov, msgs, **kw: "ok-sync")
        cfg = _cfg(providers=(ProviderCfg(
            name="main", type="fake_sync", base_url="x", model="m", api_key="k"),))
        out = await dispatch_async([{"role": "user", "content": "x"}], cfg=cfg)
        assert out == "ok-sync"

    def test_model_override_passed(self, monkeypatch):
        from stub import llm_providers

        seen = {}

        def spy(prov, msgs, model="", **kw):
            seen["model"] = model
            return "ok"

        monkeypatch.setitem(llm_providers._PROTOCOL_DISPATCH, "fake_sync", spy)
        cfg = _cfg(providers=(ProviderCfg(
            name="main", type="fake_sync", base_url="x", model="default-m", api_key="k"),))
        dispatch([{"role": "user", "content": "x"}], cfg=cfg, model="override-m")
        assert seen["model"] == "override-m"

    def test_find_provider(self):
        p = ProviderCfg(name="a", type="openai", base_url="u", model="m", api_key="k")
        assert _find_provider("a", (p,)) is p
        assert _find_provider("b", (p,)) is None


class TestChatCompat:
    def test_chat_stub_without_keys(self, monkeypatch):
        for k in ("MINIMAX_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        out = chat([{"role": "user", "content": "hi"}])
        assert "hiveswarm-MVP-stub-reply" in out  # 无 key → 明确的 stub 回复

    def test_chat_minimax_key_unreachable_returns_stub_error(self, monkeypatch):
        monkeypatch.setenv("MINIMAX_API_KEY", "k")
        monkeypatch.setenv("MINIMAX_API_BASE", "http://127.0.0.1:9")
        out = chat([{"role": "user", "content": "hi"}])
        # 真调用会失败 (不可达), chat 兼容层必须兜住返回 stub 文案, 不抛
        assert "hiveswarm-MVP-stub-reply" in out


class TestResolveOllamaSync:
    def test_sync_shell_returns_none_when_down(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_API_BASE", "http://127.0.0.1:9")
        assert resolve_ollama(None) is None  # 同步壳, 无 loop → asyncio.run 探测失败

    def test_compat_aliases_exist(self):
        from stub.llm_litellm import _resolve_minimax, _resolve_ollama
        assert _resolve_minimax() is None
        assert _resolve_ollama() is None
