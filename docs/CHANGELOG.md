## [0.2.0] - 2026-06-26

### Added
- **FastAPI 网关** (`gateway/`): 5 端点 (POST /tasks, GET /tasks/{id}, GET /skills, GET /events SSE, GET /health)
- **Python SDK** (`sdk/hiveswarm_client/`): 异步 `HiveSwarmClient` + 同步 `SyncHiveSwarmClient`
- **Gradio 战情看板** (`stub/dashboard_gradio.py`): 5 面板 (技能池/任务/事件流/健康度/提交任务)
- **agentvet_pack 技能包**: 4 个 scan skill (L1-L4), 绕开 FastAPI 直接调 scanner engine
- **Bearer Token 鉴权中间件** (`gateway/middleware/auth_bootstrap.py`): LazyAuth 模式, lifespan 后挂载, /health 豁免
- **输入校验加固**: Pydantic field_validators 拦截空 request / 路径遍历 / null byte
- **Docker 化**: `Dockerfile` (Python 3.13-slim) + `docker-compose.yml` (gateway + dashboard) + `.dockerignore`
- **SSE 取消订阅修复**: 客户端断开 → 自动 unsubscribe, 防止内存泄漏
- **EventBus unsubscribe 抽象**: `subscribe()` 返回 sub_id, `unsubscribe(sub_id)` 幂等
- **MiniMax M3 适配**: LiteLLM 路由自动检测 MINIMAX_API_KEY, 优先级 > OpenAI > Anthropic

### Changed
- `SkillPool` 加 `get_manifest(name)` 公开方法, 取代 `pool._skills` 直接访问
- `Config` dataclass 加 `gateway: GatewayCfg` 字段 + `[gateway]` 配置 section
- `stub.llm_litellm` 加 MiniMax M3 端点支持
- `stub.auth_simple.SimpleAuth` 改为 Bearer Token 字典验证 + 匿名 fallback
- `src/main.py` 提取技能注册逻辑到 `layers/work/skill_registry.py`

### Tests
- 总数: **209 条** (从 182 → 209), 1.9s 跑完
- 新增: gateway 模型 9 条 + gateway 路由 6 条 + 鉴权 3 条 + 端到端链 2 条 = 20 条

### Notes
- 网关默认端口 8000, dashboard 默认 7860
- 默认 token: `mvp-token-admin` / `mvp-token-dev` / `mvp-token-view`
- 环境变量覆盖: `HIVESWARM_TOKENS=user:role,...`
- agentvet 真实扫描全目录耗时约 6 分钟, 异步模式 (`async_mode: true`) 解决同步等待

---

## [0.1.0] - 2026-06-25

### Added
- **核心架构**: 6 层( Brain / Work / Inspect / Repair / Monitor / Memory )
  - 全部走 ABC 接口 + stub 实现,符合"日后可升级"原则
- **核心创新**: Skill 借/还 + 临时 Agent 装配(use-and-discard)
  - `SkillPool` 引用计数 + 自动 health_check + auto-retire
  - `SkillBundle` + `Borrowed` 事务,异常自动归还
  - `TempAgent` 工厂装配,跑完即销毁
  - `TaskTransaction` 编排多 subtask,失败可 abort
- **配置驱动**: `config/default.toml` + `config/mvp.toml` + `config/production.toml.example`
  - 强类型 `Config` dataclass,frozen,改 1 行 = 改行为
- **11 个 stub 占位实现** (auth/audit/billing/tenant/recovery/telemetry/governance/llm/bus/memory/dashboard)
  - 公司化 = 改 1 行配置,不动核心代码
- **Brain**: MockBrain (无 LLM key 时降级) + LLMBrain (有 key 调 LiteLLM)
- **Inspect**: 6 个基础 Validator + Checker 组合 + LLM Judge (带规则降级)
- **Repair**: StrategyTable (配置驱动) + Fixer + ReAssembler
- **Monitor**: EventLogger (JSONL append-only) + MonitorBus + HealthSnapshotter
- **Memory**: 3 层记忆 (short/working/long) + 跨层 recall
- **入口**: `python -m src.main "做一个 PPT"` 真跑通
- **测试**: 182 条单测 + 集成 + e2e,1.20s 跑完

### Notes
- 这是 MVP,所有外部依赖(LiteLLM/Gradio/FastAPI)都是 stub 或 lazy import
- 没有 Docker / 文档 / 真技能包 — 这些在 Day 6-20 补
- LLM 没 key 也能跑(MockBrain)
