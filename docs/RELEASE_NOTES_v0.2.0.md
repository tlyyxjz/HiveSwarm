# v0.2.0 Release Notes (2026-06-28)

> Day 15 蜂巢 Agent 回报后填充实际内容。本文件为占位骨架。

## ✨ Added

- **Ollama 本地模型接入** — `stub/llm_providers.py` 配置驱动 dispatch，支持 qwen3:8b + bge-m3 embedding
- **6 个公司化 stub 示例** — OAuth2/Kafka/Stripe/多租户/OpenTelemetry/Circuit-breaker
- **HOW_TO_REPLACE.md 扩展到 11 ABC 全覆盖** — 替换指南补完 Store/Governance/Memory/EventBus/SkillPool/Brain 6 场景
- **首次 git 提交 + v0.2.0 tag** — 仓库从空到正式版本

## 🔧 Changed

- **重构 stub/llm_litellm.py** — 配置驱动 dispatch(cfg)，去除硬编码
- **拆出 stub/llm_providers.py** — provider 注册表独立维护
- **CHANGELOG.md** — 补 v0.2.0 patch 段（245 → 263 测试基线）

## 🐛 Fixed

- **SSE 取消订阅修复** — 客户端断开自动 unsubscribe，防止内存泄漏
- **active_provider 找不到抛 ConfigurationError** — 之前静默返回默认
- **Ollama 集成测试跳过逻辑** — 不可达时显式 skip 而非 fail

## 📊 Stats

- 测试: 245 → 263 passed (+ 18 新单测)，3 skipped (Ollama 离线)
- stub 文件: 6 占位 → 12 完整（含 6 公司化真实示例）
- 文档: HOW_TO_REPLACE.md 409 行 → < 600 行

## ⚠️ Known Limitations

- 端到端 docker compose up 未真跑（Windows 无 WSL）
- confluent_kafka / stripe / PyJWT 用 TYPE_CHECKING 软依赖，未强制安装
- gh release 依赖 GitHub CLI 登录态