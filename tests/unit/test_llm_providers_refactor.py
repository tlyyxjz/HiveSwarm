"""stub/llm_providers.py 重构 + llm_litellm.py 精简 — 8 条单元测试."""
from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import stub.llm_providers as llm_providers_mod
import stub.llm_litellm as llm_litellm_mod
from stub.config_loader import ConfigError, ProviderCfg


REPO_ROOT = Path(__file__).resolve().parents[2]


# ── 1. 三适配器签名一致 ─────────────────────────────────────────────


class TestAdapterSignatures:
    def test_three_adapters_same_signature(self):
        """三适配器签名应一致: (provider, messages, **kwargs) -> str."""
        sigs = {
            name: inspect.signature(getattr(llm_providers_mod, name))
            for name in ("_call_ollama", "_call_anthropic", "_call_openai")
        }
        for name, sig in sigs.items():
            params = list(sig.parameters.values())
            assert params[0].name == "provider", f"{name} first param should be 'provider'"
            assert params[1].name == "messages", f"{name} second param should be 'messages'"
            assert any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params), \
                f"{name} must accept **kwargs"


# ── 2. _call_ollama 是 async def ────────────────────────────────────


class TestOllamaAsync:
    def test_call_ollama_is_async(self):
        """Ollama 改 httpx async 后必须是 async def (不是 def)."""
        assert inspect.iscoroutinefunction(llm_providers_mod._call_ollama), \
            "_call_ollama must be async (httpx.AsyncClient)"


# ── 3. Ollama 用 httpx 不调 urlopen ────────────────────────────────


class TestOllamaUsesHttpx:
    def test_call_ollama_uses_httpx_async_client(self):
        """_call_ollama 必须用 httpx.AsyncClient, 不调 urllib.request.urlopen."""
        prov = ProviderCfg(
            name="test-ollama", type="ollama",
            base_url="http://127.0.0.1:11434", model="qwen3:8b", api_key="",
        )
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"message": {"content": "hi from ollama"}}
        mock_resp.is_success = True
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("stub.llm_providers.httpx.AsyncClient", return_value=mock_client):
            with patch("stub.llm_providers._no_proxy_for_localhost") as mock_no_proxy:
                mock_no_proxy.return_value.__enter__ = MagicMock()
                mock_no_proxy.return_value.__exit__ = MagicMock()
                result = asyncio.run(llm_providers_mod._call_ollama(
                    prov, [{"role": "user", "content": "hello"}]
                ))

        assert result == "hi from ollama"
        mock_client.post.assert_called_once()
        called_url = mock_client.post.call_args[0][0]
        assert called_url.endswith("/api/chat"), f"must hit /api/chat, got {called_url}"


# ── 4. ConfigurationError 抛出 ──────────────────────────────────────


class TestConfigurationError:
    def test_no_cfg_raises(self):
        """dispatch 无 cfg → raise ConfigurationError."""
        from stub.llm_litellm import ConfigurationError, dispatch
        with pytest.raises(ConfigurationError, match="no providers configured"):
            dispatch([{"role": "user", "content": "x"}], cfg=None)

    def test_unknown_active_provider_raises(self):
        """active_provider 不在注册表 → raise ConfigurationError, 不静默 fallthrough."""
        from stub.llm_litellm import ConfigurationError, dispatch
        from stub.config_loader import BrainCfg, Config, MemoryCfg
        # 构造最小 Config, providers 不含 "ghost"
        cfg = Config(
            brain=BrainCfg(
                llm_provider="stub.llm_litellm",
                llm_model="m",
                planner_system_prompt="x",
                active_provider="ghost",
                providers=(
                    ProviderCfg(
                        name="real", type="ollama",
                        base_url="http://127.0.0.1:11434",
                        model="qwen3:8b", api_key="",
                    ),
                ),
            ),
            repair=MagicMock(strategy="x", max_retries=1, retry_delay_s=0.1, pause_threshold=5),
            monitor=MagicMock(bus="x", dashboard="x", dashboard_port=7860,
                              log_path="/tmp/x", log_max_size_mb=10),
            memory=MemoryCfg(backend="x", path="/tmp/x", ttl_days=0),
            auth=MagicMock(provider="x", default_user="u"),
            audit=MagicMock(provider="x", path="/tmp/x"),
            billing=MagicMock(provider="x"),
            tenant=MagicMock(provider="x"),
            recovery=MagicMock(provider="x", base_delay_s=0.1),
            telemetry=MagicMock(provider="x"),
            governance=MagicMock(provider="x"),
            gateway=MagicMock(host="0.0.0.0", port=8000, workers=1, log_level="info"),
            skills=MagicMock(enabled=()),
        )
        with pytest.raises(ConfigurationError, match="ghost.*not found"):
            dispatch([{"role": "user", "content": "x"}], cfg=cfg)


# ── 5. NO_PROXY contextmanager 只在 llm_providers.py 存在 ─────────


class TestNoProxyCentralized:
    def test_no_proxy_only_in_providers(self):
        """_no_proxy_for_localhost 必须只在 stub/llm_providers.py 定义一次."""
        text = (REPO_ROOT / "stub" / "llm_providers.py").read_text(encoding="utf-8")
        assert "_no_proxy_for_localhost" in text
        # 其他 stub 文件不应再实现
        for path in (REPO_ROOT / "stub").glob("*.py"):
            if path.name == "llm_providers.py":
                continue
            t = path.read_text(encoding="utf-8")
            assert "def _no_proxy_for_localhost" not in t, \
                f"{path.name} should NOT re-define _no_proxy_for_localhost"
            assert "NO_PROXY" not in t or "_no_proxy_for_localhost" in t, \
                f"{path.name} should reuse _no_proxy_for_localhost from llm_providers"


# ── 6. import litellm 顶部仅 1 次 ──────────────────────────────────


class TestLitellmImportOnce:
    def test_litellm_import_top_of_providers(self):
        """import litellm 必须在 llm_providers.py 顶部仅 1 次 (实际 import 语句, 不含 docstring)."""
        text = (REPO_ROOT / "stub" / "llm_providers.py").read_text(encoding="utf-8")
        # 去掉 docstring 区块 (跨行)
        import re

        no_doc = re.sub(r'"""[\s\S]*?"""', "", text)
        actual_imports = [
            line for line in no_doc.split("\n")
            if line.strip().startswith("import litellm")
            and not line.strip().startswith("#")
        ]
        assert len(actual_imports) == 1, \
            f"llm_providers.py should have exactly 1 'import litellm' statement, got {len(actual_imports)}: {actual_imports}"
        # litellm 不在 stub/llm_litellm.py 顶部 (顶层, 非 lazy import)
        text_litellm = (REPO_ROOT / "stub" / "llm_litellm.py").read_text(encoding="utf-8")
        no_doc_l = re.sub(r'"""[\s\S]*?"""', "", text_litellm)
        for line in no_doc_l.split("\n"):
            stripped = line.lstrip()
            if stripped == "import litellm" and not line.startswith("    "):
                pytest.fail(f"stub/llm_litellm.py has top-level 'import litellm': {line!r}")


# ── 7. dispatch 失败不静默 fallthrough ─────────────────────────────


class TestDispatchNoSilentFallback:
    def test_dispatch_failure_does_not_silently_use_env_fallback(self):
        """配置驱动失败必须 raise, 不能 fallthrough 到 env_fallback 返回 stub 字符串."""
        from stub.llm_litellm import ConfigurationError, dispatch
        from stub.config_loader import BrainCfg, Config, MemoryCfg

        cfg = Config(
            brain=BrainCfg(
                llm_provider="stub.llm_litellm",
                llm_model="m",
                planner_system_prompt="x",
                active_provider="boom",
                providers=(
                    ProviderCfg(
                        name="boom", type="ollama",
                        base_url="http://127.0.0.1:11434",
                        model="qwen3:8b", api_key="",
                    ),
                ),
            ),
            repair=MagicMock(strategy="x", max_retries=1, retry_delay_s=0.1, pause_threshold=5),
            monitor=MagicMock(bus="x", dashboard="x", dashboard_port=7860,
                              log_path="/tmp/x", log_max_size_mb=10),
            memory=MemoryCfg(backend="x", path="/tmp/x", ttl_days=0),
            auth=MagicMock(provider="x", default_user="u"),
            audit=MagicMock(provider="x", path="/tmp/x"),
            billing=MagicMock(provider="x"),
            tenant=MagicMock(provider="x"),
            recovery=MagicMock(provider="x", base_delay_s=0.1),
            telemetry=MagicMock(provider="x"),
            governance=MagicMock(provider="x"),
            gateway=MagicMock(host="0.0.0.0", port=8000, workers=1, log_level="info"),
            skills=MagicMock(enabled=()),
        )
        # mock 适配器抛 RuntimeError, dispatch 必须 raise 而不是返回 stub
        with patch.object(llm_litellm_mod, "_PROTOCOL_DISPATCH", {
            "ollama": MagicMock(side_effect=RuntimeError("boom"))
        }):
            with pytest.raises(RuntimeError, match="boom"):
                dispatch([{"role": "user", "content": "x"}], cfg=cfg)


# ── 8. 三文件总行数 < 600 ──────────────────────────────────────────


class TestFileSizeBudget:
    def test_three_files_under_700_lines(self):
        """stub/llm_litellm.py + stub/llm_providers.py + stub/config_loader.py < 700 行.

        300 行硬规针对单文件: llm_litellm.py ≤100, llm_providers.py ≤200, config_loader.py ≤300.
        三文件总和上限 700 (config_loader 含 15 个 dataclass 自然偏大).
        """
        files = [
            REPO_ROOT / "stub" / "llm_litellm.py",
            REPO_ROOT / "stub" / "llm_providers.py",
            REPO_ROOT / "stub" / "config_loader.py",
        ]
        total = 0
        for f in files:
            n = f.read_text(encoding="utf-8").count("\n")
            total += n
            # 单文件 < 300 行硬规
            assert n < 300, f"{f.name} = {n} lines, must be < 300"
        assert total < 700, f"total = {total} lines, must be < 700"