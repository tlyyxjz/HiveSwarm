# HiveSwarm 五档定价方案 + 缺陷审查 + 未来升级路线

---

# 一、五档定价方案

## 1.1 五档定义

| 档位 | 名称 | 并发Agent | 月配额(任务) | 适用 |
|------|------|-----------|-------------|------|
| **Tier 1** | Free 免费 | 3 | 50 | 个人试用 |
| **Tier 2** | Starter 入门 | 7 | 200 | 小团队 |
| **Tier 3** | Pro 专业 | 15 | 1,000 | 中型部门 |
| **Tier 4** | Business 企业 | 25 | 5,000 | 大公司 |
| **Tier 5** | Enterprise 旗舰 | 50 | 无限 | 平台级 |

**并发Agent = 同一时刻最多跑多少个临时Agent。** 比如 Free 用户发任务拆成 4 个 subtask → 先跑 3 个，第 4 个排队等。

## 1.2 现有架构已经预留的东西

| 已有接口 | 文件 | 怎么用 |
|----------|------|--------|
| `TenantContext` | core/tenant.py | 租户隔离，`tenant.plan = "free/pro/enterprise"` 字段已经存在 |
| `BillingMeter` | core/billing.py | 用量计量 `UsageRecord` 已经有 `user_id`/`skill_name`/`tokens` |
| `SkillPool.max_concurrent_per_skill` | layers/work/pool.py | 现在是全局 100，改成读档位配置 |
| `Config` + `load_config()` | stub/config_loader.py | TOML 配置驱动，加 section 就生效 |

## 1.3 要改的四个地方

### 改1: core/billing.py — 加并发额度字段

```python
@dataclass(frozen=True)
class TenantPlan:
    name: str                    # "free" / "starter" / "pro" / "business" / "enterprise"
    max_concurrent: int          # 3 / 7 / 15 / 25 / 50
    monthly_task_quota: int      # 50 / 200 / 1000 / 5000 / -1

TIER_CONFIG = {
    "free":       TenantPlan("free", 3, 50),
    "starter":    TenantPlan("starter", 7, 200),
    "pro":        TenantPlan("pro", 15, 1_000),
    "business":   TenantPlan("business", 25, 5_000),
    "enterprise": TenantPlan("enterprise", 50, -1),
}
```

### 改2: layers/work/pool.py — 初始化时读租户档位

```python
def __init__(self, ..., tenant_plan: TenantPlan | None = None):
    self._max_concurrent = tenant_plan.max_concurrent if tenant_plan else 100
```

### 改3: config/default.toml — 加 `[billing]` 档位

```toml
[billing]
provider = "stub.billing_noop"
default_plan = "free"  # 未指定租户的默认档
```

### 改4: gateway — 创建任务前查额度

TaskTransaction 前：`if plan.current_running >= tenant_plan.max_concurrent → 429 Too Many Requests`

## 1.4 不改的东西

- Brain 拆任务逻辑
- Skill 借还机制
- Inspect/Repair/Monitor/Memory
- FastAPI 路由
- SDK 客户端
- Gradio 看板

---

# 二、缺陷审查（诚实版）

## 2.1 影响可用性的

| 问题 | 严重度 | 说明 |
|------|--------|------|
| 网关零鉴权 | 🔴 高 | 谁调都行，生产环境直接裸奔。任何人不带 token 都能调 POST /tasks |
| SSE 内存泄漏 | 🔴 高 | subscribe 后永不 unsubscribe，长期跑会 OOM |
| sync/async 混用 | 🟡 中 | `TaskTransaction` 是同步 `with` 块，网关里丢进 `asyncio.to_thread()` 跑——能工作但线程池可能耗尽 |
| `asyncio.run()` 嵌套 | 🟡 中 | `SubtaskRunner.run()` 内部 `asyncio.run(agent.run(...))`，在已有事件循环的网关里会崩，现在靠 `run_in_executor` 绕过 |
| TestClient 不触发 lifespan | 🟡 中 | 测试里 `app.state.pool` 为 None，路由拿到就崩。当前测试刚好没测到这个路径 |

## 2.2 影响完整性的

| 问题 | 严重度 | 说明 |
|------|--------|------|
| 端到端链未验证 | 🔴 高 | agentvet→gateway→dashboard 整条链路没实际跑过一次，存在集成断裂风险 |
| 无压力测试 | 🟡 中 | 50 并发 Agent 同时跑会不会死锁、OOM、引用计数错乱——完全没测过 |
| agentvet 扫描 372 秒 | 🟡 中 | HTTP 请求等 6 分钟不现实，必须异步化 |
| 跨线程安全 | 🟡 中 | `SkillPool` 用 `threading.Lock`，但 SSE 的 `asyncio.Queue.put_nowait()` 从同步线程调——文档说线程安全但没验证 |

## 2.3 影响交付物质量的

| 问题 | 严重度 | 说明 |
|------|--------|------|
| SDK import gateway/models | 🟡 中 | 发给第三方装直接 `ImportError`，必须复制模型或改成独立包 |
| 路由用 Request.app.state | 🟢 低 | 不是正经 FastAPI Depends DI，测试时不好 mock |
| Gradio 看板无实时刷新 | 🟢 低 | 按钮手动刷新，不是 websocket/轮询自动更新 |
| 4 个空壳文件 | 🟢 低 | gateway/__init__.py, sdk/__init__.py, crawler_pack, ppt_pack — 纯占位 |
| docstring 密度不统一 | 🟢 低 | stub 有详细注释，gateway 路由没有 |
| CHANGELOG 停在 Day 5 | 🟢 低 | 干了 15 个新文件一个字没记 |

## 2.4 基础设施缺失

| 缺失项 | 影响 |
|--------|------|
| 无 Dockerfile | 别人装不了——要手动装 Python + 9 个依赖 + pip install agentvet |
| 无 docker-compose | gateway + dashboard + memory 三个服务要手启 |
| 无 .gitignore 完整检查 | 有但没检查 __pycache__ 是否真的没提交 |
| 无 CI 除 test.yml 外的东西 | 没有 lint gate / 类型检查 gate / 构建检查 |

---

# 三、未来升级方向

## 3.1 近期（1-2 周，改代码量小、收益大）

| 方向 | 为什么 | 改动量 |
|------|--------|--------|
| **Bearer Token 鉴权** | 第一天就该有。gateway/middleware/auth.py 50 行 | 小 |
| **输入校验加固** | 防路径遍历、防注入、防超大请求。Pydantic validators 20 行 | 小 |
| **Docker 化** | 别人一条命令装好。Dockerfile + docker-compose 30 行 | 小 |
| **异步 agentvet** | 372 秒→后台跑，前端轮询状态。FastAPI BackgroundTasks 10 行 | 小 |
| **SSE 修复** | subscribe 后注册 unsubscribe，防止内存泄漏。routes_events.py 加 10 行 | 小 |
| **SDK 去 gateway 依赖** | 复制 models 到 SDK 或提成独立 models 包。20 行 | 小 |
| **压力测试脚本** | locust 或简单 `asyncio.gather` 并发 100 任务，看会不会炸 | 中 |

## 3.2 中期（1-3 月，加新能力）

| 方向 | 为什么 | 改动量 |
|------|--------|--------|
| **任务队列** | 现在是同步跑（等 6 分钟），换成 Celery/Redis Queue → POST /tasks 立刻返回 task_id，前端轮询 | 中 |
| **WebSocket 替换 SSE** | 双向通信 + 自动重连 + 浏览器原生支持。events.py + routes_events.py 重写 | 中 |
| **时间旅行回放** | `EventBus.replay(since_ts)` 接口已经有了，看板接一下就行。dashboard_gradio.py 加一个时间轴面板 | 小 |
| **Gradio→React 迁移** | Gradio 适合原型，生产环境需要 React 前端。React 前端读 /skills /tasks /events 三个 endpoint 就行 | 大 |
| **多租户隔离** | `TenantContext` ABC 已有 + `Tenant.plan` 已有。加个 `MultiTenantStore` stub → 每个租户独立配额 + 独立技能池 | 中 |
| **crawler_pack 实现** | 方案 Y 的"GitHub 收割机"——gh API 搜 langchain/openai function/claude tool 项目 → 喂给 agentvet 扫 | 中 |
| **第三方技能市场** | 别人可以 `pip install hiveswarm-skill-xxx` → `pool.register(...)` 自动发现 | 中 |

## 3.3 远期（3-12 月，产品化）

| 方向 | 为什么 |
|------|--------|
| **SaaS 多租户** | 五档定价 + Stripe 计费 + OAuth 登录 → 一个域名服务 1000 个公司 |
| **技能版本化** | `SkillManifest.api_version = "1.0"` 已有 → 加语义版本 + 兼容矩阵，技能可独立升级不炸 |
| **Agent 记忆跨 session** | `MemoryStore` 3 层已有多租户前缀 → 加向量检索（Qdrant）→ agent 记得上个月的对话 |
| **人机协同 (pause point)** | `EventType.PAUSE_POINT` 已有 → 关键决策点暂停 → 微信/邮件通知人审批 → 人点了继续跑 |
| **技能编排 DSL** | 不是 "拆 4 个 subtask 串行"，而是用 YAML 描述 DAG："先跑 A→ B 和 C 并行→ 结果合并→ D 收尾" |
| **联邦蜂巢** | 多个 HiveSwarm 实例互连 → A 公司的蜂巢可以把子任务外包给 B 公司的蜂巢 → 区块链/合约结算 |
| **安全合规认证** | SOC2 / ISO 27001 审计日志(AuditLogger 已预留) + 数据保留策略(DataRetention 已预留) |

---

# 四、总结

**现在能卖的是**: 一个能跑的 MVP——借还技能、拆任务、网关 5 端点、看板 5 面板、202 测试全绿。

**卖之前必须先修的**: 鉴权、SSE 泄漏、Docker 化——这三样加起来不超过 2 小时，不修没法给客户看。

**长期天花板**: 从"个人工作台"演进到"多租户 SaaS + 技能市场 + 联邦蜂巢"的路线已经铺好了——13 个 ABC 接口就是 13 个升级点，改一行配置换一个实现。
