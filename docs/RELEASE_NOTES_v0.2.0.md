# v0.2.0 Release Notes (2026-06-28)

HiveSwarm v0.2.0 brings Ollama local model integration, configurable LLM dispatch, and the first stable multi-agent framework release.

## ✨ Added

- **Refactored `stub/llm_litellm.py` + new `stub/llm_providers.py`** — three protocol adapters (anthropic / ollama / openai) with unified signature `(provider, messages, **kwargs) -> str`
- **Async httpx Ollama support** — replaces sync `urllib`, no more event loop blocking
- **`NO_PROXY` DRY** — single implementation in `stub/llm_providers.py`, reused via import (was duplicated 17 lines × 2 files)
- **`MemoryCfg` dataclass + `batch_size=20` + `window_days=30`** — `recall_semantic` now supports batched embedding and time-window filtering
- **`dispatch_async`** — fixes gateway async loop conflict (`asyncio.run` inside running loop warning)
- **`_has_key` Ollama reachability ping** — actually probes Ollama port instead of just checking cfg registration
- **三玖 working rules `~/.claude/rules/ollama-usage.md`** — Ollama-first workflow, HTTP fallback to CLI, 91 行规则下次会话生效

## 🔧 Changed

- `stub/llm_litellm.py` 264 → 212 行 (含 50 行 backward-compatible shim, 删除会破坏旧测试)
- `stub/llm_providers.py` 新文件 147 行 — provider registry + unified adapters + 唯一 NO_PROXY 实现
- `layers/brain/planner.py` 218 → 223 行 — `_extract_json` 第 3 条正则改非贪婪 + `exc_info=True` 全覆盖
- `layers/memory/recall.py` 135 → 172 行 — 删 NO_PROXY 重复 + 加 batch_size / 时间窗口过滤
- 测试基线 230 → 245 passed (+ 15 单测)

## 🐛 Fixed

- **NO_PROXY 重复实现删除** — `llm_litellm.py` 和 `recall.py` 各 17 行重复 contextmanager → import 复用
- **Ollama 同步阻塞** — `_call_ollama` 改 async，长任务并发请求不再串行化
- **`active_provider` 找不到静默用第一个** → 抛 `ConfigurationError`
- **`dispatch` 配置驱动失败不再静默 fallthrough 到 env_fallback**
- **Ollama HTTP 502 根因诊断**: `ollama-bridge.py` 僵尸 PID 44968 占着 11435 → taskkill 释放 + `OLLAMA_HOST=127.0.0.1:11435` 永久环境变量 + curl `--noproxy '*'` 绕开系统 `HTTP_PROXY=127.0.0.1:7897`

## 📊 Stats

- 测试: 230 → 245 passed (+ 15 新单测), 3 skipped (Ollama HTTP 502 容错)
- git commits: 0 → 2 (`de86fff` 初始 + `6468848` docs)
- 五关门禁全过: DRY ✅ / 异常(exc_info 全覆盖)✅ / 线程(无新共享数据)✅ / 资源(import 顶部 1 次)✅ / 验证(245+3)✅
- 300 行硬规全守: 最大 293 行 (`stub/config_loader.py`)

## ⚠️ Known Limitations

- 端到端 docker compose up 未真跑 (Windows 无 WSL)
- Ollama HTTP 调用必须 `curl --noproxy '*'` 绕开系统 HTTP_PROXY
- qwen3:8b 8B 模型在 strict format 任务上"健谈"——`thinking` 模式默认开吃 num_predict，主线程手工校
- confluent_kafka / stripe / PyJWT 等真实集成库用 TYPE_CHECKING 软依赖，待 Day 16+ 派 day15-exec Agent 补 6 公司化 stub
