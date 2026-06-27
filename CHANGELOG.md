# Changelog

All notable changes to HiveSwarm will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/lang/zh-CN/).

---

## [Unreleased]

### Added
- **拆 `stub/llm_litellm.py` → `dispatch` 入口 + 新 `stub/llm_providers.py` 三协议适配器**：anthropic/ollama/openai 统一签名 `(provider, messages, **kwargs) -> str`，Ollama 用 httpx.AsyncClient + await 异步调用（替代同步 urllib 阻塞 event loop）。
- **NO_PROXY 单一实现** (`stub/llm_providers.py`)：上下文管理器唯一实现，`layers/memory/recall.py` 改为 `from stub.llm_providers import _no_proxy_for_localhost` 复用，消除 DRY 违反。
- **全部 `except` 加 `exc_info=True`**：dispatch / dispatch_async / chat env_fallback / planner / recall 共 8 处异常日志增强，便于事后诊断。
- **`MemoryCfg` dataclass** (`stub/config_loader.py` + `config/default.toml`)：新增 `embedding_model` / `batch_size=20` / `window_days=30` 三个字段，`recall_semantic` 加批量嵌入 + 时间窗口过滤避免 OOM。
- **`dispatch_async` + `_has_key` 可达性 ping**：新加 `dispatch_async` 修复 gateway async loop 冲突；`LLMBrain._has_key` 改用 `httpx.AsyncClient` 短超时真测 Ollama 端口，不只看 cfg 注册表是否存在。
- **三玖工作方式规则** (`~/.claude/rules/ollama-usage.md`)：91 行规则文件，下次会话生效——简单任务走 Ollama / 代码改动派 PI-dev / 模板文档 Ollama 起草 + 主线程校。

### Changed
- `stub/llm_litellm.py` 从 264 行精简到 212 行（含 50 行向后兼容 shim，删会破坏旧测试）。
- `stub/llm_providers.py` 新文件 147 行，三协议适配器 + 统一接口 + 唯一 NO_PROXY 实现。
- `layers/brain/planner.py` 218 → 223 行（`_extract_json` 第 3 条正则改非贪婪 + exc_info 全覆盖）。
- `layers/memory/recall.py` 135 → 172 行（删 NO_PROXY 重复 + 加 batch_size / 时间窗口过滤）。

### Fixed
- **NO_PROXY 重复实现删除**：之前 `llm_litellm.py` 和 `recall.py` 各有一份 17 行 NO_PROXY contextmanager，改 import 复用后消除。
- **Ollama 同步阻塞 → async**：`_call_ollama` 改用 `httpx.AsyncClient + await`，不再阻塞 event loop（长任务跑批时全部并发请求不再被串行化）。
- **`active_provider` 配错静默用第一个** → 抛 `ConfigurationError`（实现细节：dispatch 配置驱动失败不再 fallthrough 到 env_fallback 静默降级）。

---

## [0.1.0] - 2026-06-26

### Added
- **FastAPI HTTP 网关** (`gateway/`): 工厂函数 `create_app()` + lifespan 管理，5 个端点：
  - `POST /tasks/` — 提交任务，支持 `async_mode=true` 异步模式
  - `GET /tasks/{task_id}` — 取回任务结果
  - `GET /skills/` — 列出已注册技能及健康度
  - `GET /events` — SSE 实时事件流
  - `GET /health` — 健康检查（无需鉴权）
- **Bearer Token 鉴权中间件** (`gateway/middleware/auth_bootstrap.py`): `LazyAuthMiddleware` 拦截所有非豁免路径（`/health`、`/docs`、`/openapi.json`），从 `Authorization: Bearer <token>` 提取 token 调 `services.auth.check_token()`，无 token 返回 401，无效 token 返回 401。
- **MVP Token 配置**: 内置 3 个 token（`mvp-token-admin` / `mvp-token-dev` / `mvp-token-view`），支持环境变量 `HIVESWARM_TOKENS=user:role,...` 自定义。
- **输入校验加固** (`gateway/models.py`): Pydantic `field_validators` 拦截空 request、路径遍历 `..`、null byte 注入，`request` 限长 2000 字符，`target` 限长 500 字符。
- **Python SDK** (`sdk/hiveswarm_client/`): 异步 `HiveSwarmClient` + 同步 `SyncHiveSwarmClient`，`submit_task()` / `get_task()` / `list_skills()` / `stream_events()` / `health()` 5 个方法对应 5 个端点。
- **Gradio 战情看板** (`stub/dashboard_gradio.py`): 5 面板——技能池（表格）、最近任务（10 条）、事件流（20 条）、健康度指标、提交任务表单。
- **agentvet_pack 技能包** (`skills/agentvet_pack/`): 4 个真实 scan skill（L1-L4），绕开 FastAPI 直接调 agentvet scanner engine，含 `pyproject.toml`、`manifest.toml`。
- **crawler_pack 技能包骨架** (`skills/crawler_pack/`): 占位结构（`pyproject.toml` + `manifest.toml` + `__init__.py`），skills.py 待实现。
- **Docker 化**: `Dockerfile`（Python 3.13-slim 多阶段构建，EXPOSE 8000 7860）+ `docker-compose.yml`（gateway + dashboard 双服务编排 + 持久化数据卷 hive-data）+ `.dockerignore`。
- **SSE 取消订阅修复** (`gateway/routes_events.py`): `StreamingResponse` 生成器捕获 `asyncio.CancelledError` → 遍历所有 `sub_ids` 调 `bus.unsubscribe()`，防止客户端断开后内存泄漏。
- **EventBus unsubscribe** (`core/events.py`): `subscribe()` 返回 `sub_id`，新增 `unsubscribe(event_type, sub_id)` 方法（幂等，重复取消为 noop）。
- **技能注册器** (`layers/work/skill_registry.py`): 从 `src/main.py` 提取，`register_needed_skills()` 根据 Plan 的 `required_skills` 优先加载真实技能包，失败回退 Mock `_EchoSkill`。CLI 和 Gateway 共用。
- **MiniMax M3 适配** (`stub/llm_litellm.py`): LiteLLM 路由自动检测 `MINIMAX_API_KEY`，通过 `openai/minimax-m3-plus` 端点调用，优先级高于 OpenAI/Anthropic。
- **Gateway 配置 section** (`config/default.toml`): 新增 `[gateway]` section（host / port / workers / log_level）。
- **端到端路由集成测试** (`tests/integration/test_gateway_routes.py`): 6 条——health / skills / tasks POST / tasks GET / 404 / events。
- **Gateway 模型单测** (`tests/unit/test_gateway_models.py`): 9 条 Pydantic 模型验证（空 request / 路径遍历 / null byte / 超长等）。

### Changed
- `SkillPool` 新增 `get_manifest(name)` 公开方法，替代外部直接访问 `pool._skills`。
- `Config` dataclass 新增 `gateway: GatewayCfg` 字段。
- `stub/auth_simple.SimpleAuth` 改为 Bearer Token 字典验证（支持 `HIVESWARM_TOKENS` 环境变量）+ 匿名 fallback。
- `src/main.py` 技能注册逻辑提取到 `layers/work/skill_registry.py`。

### Fixed
- SSE 端点客户端断开后 `asyncio.Queue` 未清理，subscriber 永不释放——现通过 `CancelledError` 处理 + `unsubscribe()` 修复。
- Gateway 路由依赖 `app.state` 在 TestClient 下可能为 None——通过 lifespan 保证 startup 初始化。

---

## [0.0.1] - 2026-06-25

### Added
- **11 个核心 ABC 接口** (`core/`): 只定义契约不实现，签名一旦发布不可改（只能加新方法）：
  - `AuthProvider` — 验 token 返回 `UserContext`
  - `AuditLogger` — 写审计日志（谁/何时/做什么）+ 查询
  - `BillingMeter` — 按 token/任务/技能调用计量
  - `TenantContext` — 多租户隔离 + 技能白名单
  - `RecoveryStrategy` — retry/circuit-breaker/fallback
  - `Tracer` — 链路追踪 + 计数 + 直方图
  - `DataRetention` — 数据保留策略 + PII 脱敏
  - `Skill` + `SkillManifest` + `SkillHealth` — 技能契约
  - `Agent` — 临时智能体（`run` + `destroy`）
  - `Brain` — 拆任务（`plan`）+ 失败决策（`decide`）
  - `EventBus` — 跨层事件总线（publish/subscribe/replay）
- **11 个 Stub 占位实现** (`stub/`): 全 ABC 都有可运行的 MVP 实现，公司化 = 加新 stub + 改 1 行 config，核心代码零修改。
  - `SimpleAuth` — 永远返回 admin
  - `LogFileAudit` — 本地 JSONL 审计日志
  - `NoopBilling` — 空计费
  - `DefaultTenant` — 默认单租户
  - `RetryRecovery` — 重试 N 次 + 指数退避
  - `NoopTelemetry` — 空遥测
  - `PermanentRetention` — 永久保留 + PII 哨兵
  - `LocalEventBus` — 线程安全内存事件总线
  - `SQLiteStore` — Key-Value 持久化
  - `LiteLLMAdapter` — 调 OpenAI/Anthropic 等 LLM
  - `GradioDashboard` — 5 面板战情看板
- **配置驱动系统**: `config/default.toml`（基线）+ `config/mvp.toml`（覆盖）+ `config/production.toml.example`（模板），强类型 `Config` dataclass（frozen），TOML 加载器 `stub/config_loader.py`。
- **Services 聚合根** (`stub/services.py`): 跟 Miku 桌宠 `AppServices` 同套路，`build_default_services()` 统一构造 11 个 stub。
- **6 层业务架构** (`layers/`):
  - **Brain（大脑）**: `MockBrain`（关键词匹配降级）+ `LLMBrain`（LiteLLM 真模型）→ 输出 `Plan`（DAG of `SubTask`）
  - **Work（工作）**: `SkillPool`（引用计数 checkout/return_back + 自动 health_check + auto-retire）+ `AgentFactory`（assemble `TempAgent` → destroy）+ `TaskTransaction`（with 块编排多 subtask，失败 abort 全还）
  - **Inspect（检查）**: 6 个 `Validator`（not_empty / has_keys / match_pattern / in_range / no_duplicates / type_check）+ `Checker` 组合 + `LLMJudge`（有 key 调 LLM，无 key 降级到规则）
  - **Repair（修补）**: `StrategyTable`（配置驱动错误关键词 → 动作映射）+ `Fixer`（switch/reassemble/halt）+ `ReAssembler`（换 skill 重试）
  - **Monitor（监察）**: `MonitorBus`（EventBus → EventLogger 粘合）+ `EventLogger`（JSONL append-only）+ `HealthSnapshotter`
  - **Memory（记忆）**: `MemoryStore`（3 层：short/working/long）+ 跨层 `recall`（by_key / by_prefix / by_ts）
- **核心创新——Skill 借/还机制**:
  - `SkillBundle` + `Borrowed` 上下文管理器：借出 N 个 skill，异常自动归还，引用计数 +1/-1
  - `SkillPool.checkout()`: 多 skill 一起借，全成功才 +1，任一失败全回滚
  - `Borrowed.__exit__`: 二次还幂等（noop），防止双层清理炸
  - `TempAgent`: 一次性使用，`destroy()` 后调 `run()` 抛 `AgentAlreadyDestroyedError`
  - 并发安全：`threading.Lock` 保护引用计数，单 skill 上限 `max_concurrent_per_skill=100`
- **CLI 入口** (`src/main.py`): `python -m src.main "做一个 PPT"` 6 步全链（注册技能 → Brain 拆 → Work 跑 → Inspect 查 → Repair 修 → 输出结果），无 LLM key 也能跑（MockBrain 降级）。
- **4 份核心文档** (`docs/`):
  - `VISION.md` — 产品愿景 + 核心差异 vs AutoGen/CrewAI
  - `ARCH.md` — 6 层架构详解 + 正常/失败数据流图 + 借还机制不变量
  - `INTERFACES.md` — 11 个 ABC 接口契约 + 替换原则 + 常见错误
  - `HOW_TO_REPLACE.md` — 5 个真实替换场景（Auth→OAuth、Audit→Kafka、Billing→Stripe、Memory→Qdrant、Bus→Kafka）
- **CI** (`.github/workflows/test.yml`): push 触发 pytest，矩阵 Python 3.10/3.11/3.12。
- **测试金字塔**: 182 条测试，1.20s 跑完。
  - Unit: 171 条（test_interfaces 269 行 / test_pool 224 行 / test_skill_bundle 157 行 / test_factory 152 行 / test_transaction 138 行 / test_brain 158 行 / test_inspect 192 行 / test_repair 122 行 / test_monitor 143 行 / test_memory 112 行 / test_main 56 行 / test_config_loader 42 行 / test_brain_dag）
  - Integration: 8 条（test_work_e2e 161 行 / test_brain_work_e2e 98 行）
  - E2E: 3 条（test_full_hiveswarm 210 行——6 层全链 Brain→Work→Inspect→Repair→Monitor→Memory）

[Unreleased]: https://github.com/sanjiu/hiveswarm/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/sanjiu/hiveswarm/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/sanjiu/hiveswarm/releases/tag/v0.0.1
