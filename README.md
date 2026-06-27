# HiveSwarm

> Multi-agent coordination framework with **dynamic skill equipping** (borrow/return) and **use-and-discard** agents.

## 核心创新

跟 AutoGen / CrewAI 的核心区别:**Skills are borrowed, not bound.**

```
[任务] → [大脑拆分]
  → [技能池] 借出需要的 N 个 skill
  → [工厂] 临时组装 Agent-001 (带这 N 个 skill)
  → [Agent 执行] 任务完成
  → [归还 skill] 销毁 Agent-001
  → [下一个 Agent-002] 借另外 M 个 skill
```

**为什么这很关键**: Skills 太多时,无法预先给每个 Agent 装好;动态按需借,任务结束归还,资源不泄漏。

## 快速开始(5 步)

### Step 1: 装 Python 依赖

```bash
cd C:/Users/Lenovo/Desktop/hiveswarm
pip install pydantic litellm fastapi uvicorn httpx
pip install pytest pytest-asyncio pytest-cov
pip install python-pptx  # 可选: PPT 生成 (ppt_pack)
```

### Step 2: 跑测试(验证环境)

```bash
python -m pytest --tb=short -q
```

期望:`230 passed`

### Step 3: 跑 demo(看效果)

```bash
python -m src.main "帮我做一个 PPT"
```

输出:
```
Task ID: mock-xxxx
Rationale: mock brain (no LLM key configured)
Subtasks (4): s1, s2, s3, s4
Result: [OK] all passed
  [OK] s1
  [OK] s2
  [OK] s3
  [OK] s4
```

### Step 4: 配 LLM(可选,没 key 也行)

优先级: MiniMax M3 > Ollama (qwen3:8b 对话 + bge-m3 嵌入) > OpenAI > Anthropic > MockBrain 降级

```bash
# MiniMax M3 (推荐)
set MINIMAX_API_KEY=sk-cp-xxxxx              # Windows cmd
export MINIMAX_API_KEY=sk-cp-xxxxx            # Linux/Mac
# 可选: MINIMAX_API_BASE / MINIMAX_MODEL

# OpenAI (备选)
set OPENAI_API_KEY=sk-xxxx

# Anthropic (备选)
set ANTHROPIC_API_KEY=sk-ant-xxxx
```

有 key → 调真 LLM 拆任务(更聪明);无 key → MockBrain 降级。

**Ollama 本地模型**(无需 API Key):
```bash
# 装 Ollama + 拉模型
ollama pull qwen3:8b     # 对话模型
ollama pull bge-m3        # 嵌入模型(语义搜索)
```
自动检测 `OLLAMA_API_BASE`(默认 `http://127.0.0.1:11434`),不可达自动跳过。

### Step 5: 改 config(可选,默认 mvp.toml)

```bash
# 改行为, 不动 Python
notepad config/mvp.toml
```

---

## HTTP API 网关

5 个端点,所有非 /health 路径都需要 Bearer Token。

### 启动

```bash
python -m gateway              # 默认 127.0.0.1:8000
```

### 鉴权 token (MVP)

| Token | 角色 |
|-------|------|
| `mvp-token-admin` | admin (全权限) |
| `mvp-token-dev` | developer |
| `mvp-token-view` | viewer |

自定义: 环境变量 `HIVESWARM_TOKENS=user:role,user:role`

### 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/tasks/` | 提交任务,可选 `async_mode=true` 异步 |
| `GET` | `/tasks/{task_id}` | 取回任务结果 |
| `GET` | `/skills/` | 列出已注册 skill + 健康度 |
| `GET` | `/events` | SSE 事件流 |
| `GET` | `/health` | 健康检查(无需鉴权) |

### 示例

```bash
# 提交 PPT 任务
curl -X POST http://127.0.0.1:8000/tasks/ \
  -H "Authorization: Bearer mvp-token-admin" \
  -H "Content-Type: application/json" \
  -d '{"request": "帮我做一个PPT"}'

# 列出 skills
curl http://127.0.0.1:8000/skills/ \
  -H "Authorization: Bearer mvp-token-admin"

# 无 token 应被拒
curl -X POST http://127.0.0.1:8000/tasks/ \
  -H "Content-Type: application/json" \
  -d '{"request": "hi"}'
# → 401 {"detail":"missing Bearer token"}
```

### Python SDK

```bash
# 异步
from sdk.hiveswarm_client import HiveSwarmClient
async with HiveSwarmClient("http://127.0.0.1:8000") as c:
    result = await c.submit_task("做一个PPT")
    print(result.task_id)

# 同步
from sdk.hiveswarm_client import SyncHiveSwarmClient
c = SyncHiveSwarmClient("http://127.0.0.1:8000")
result = c.submit_task("做一个PPT")
```

---

## Gradio 战情看板

```bash
python -c "from stub.dashboard_gradio import GradioDashboard; \
  GradioDashboard(port=7860).launch()"
```

5 面板: 技能池 / 任务 / 事件流 / 健康度 / 提交任务。
默认静态刷新,点击按钮更新。

---

## Docker

```bash
# 构建 + 启动 gateway + dashboard
docker compose up

# 只启动 gateway
docker build -t hiveswarm .
docker run -p 8000:8000 -p 7860:7860 hiveswarm
```

端口: gateway 8000,dashboard 7860。
数据卷: `hive-data` (持久化 SQLite + 日志)。

---

## 项目结构

```
hiveswarm/
├── core/                    # 11 个 ABC 接口(只定义, 不实现)
│   ├── auth.py              # AuthProvider
│   ├── audit.py             # AuditLogger
│   ├── billing.py           # BillingMeter
│   ├── tenant.py            # TenantContext
│   ├── recovery.py          # RecoveryStrategy
│   ├── telemetry.py         # Tracer
│   ├── governance.py        # DataRetention
│   ├── skill.py             # Skill + SkillManifest + SkillHealth
│   ├── skill_bundle.py      # SkillBundle + Borrowed
│   ├── agent.py             # Agent
│   ├── brain.py             # Brain + Plan + SubTask
│   └── events.py            # EventBus + Event
│
├── layers/                  # 6 层业务逻辑
│   ├── brain/               # 拆任务 + 决策
│   ├── work/                # 借/装/跑/还
│   ├── inspect/             # 检查
│   ├── repair/              # 修补
│   ├── monitor/             # 监察
│   └── memory/              # 记忆
│
├── stub/                    # MVP 占位实现(11 个)
│   ├── auth_simple.py       # 永远 admin
│   ├── audit_logfile.py     # 本地 JSONL
│   ├── ...
│   └── services.py          # 聚合根(跟 Miku 桌宠 AppServices 同套路)
│
├── config/                  # 配置(策略驱动, 不写死)
│   ├── default.toml         # 基线
│   ├── mvp.toml             # MVP 用(全 stub)
│   └── production.toml.example  # 公司用占位
│
├── tests/                   # 测试金字塔
│   ├── unit/                # 70% — 纯函数(< 5s)
│   ├── integration/         # 20% — 多层(< 30s)
│   └── e2e/                 # 10% — 6 层全链(< 2min)
│
├── docs/                    # 文档
│   ├── VISION.md            # 产品愿景
│   ├── ARCH.md              # 架构详解
│   ├── INTERFACES.md        # 11 个 ABC 接口清单
│   ├── HOW_TO_REPLACE.md    # 替换 stub 指南
│   └── CHANGELOG.md         # 升级日志
│
├── gateway/                 # FastAPI HTTP 网关
│   ├── app.py               # create_app() 工厂 + lifespan
│   ├── deps.py              # Depends 辅助
│   ├── models.py            # Pydantic 请求/响应模型 + 输入校验
│   ├── middleware/
│   │   └── auth_bootstrap.py  # Bearer Token 鉴权
│   └── routes_*.py          # tasks / skills / events / health
│
├── sdk/                     # Python SDK
│   └── hiveswarm_client/
│       ├── client.py        # async + sync 客户端
│       └── __init__.py      # 导出 HiveSwarmClient / SyncHiveSwarmClient
│
├── src/                     # CLI 入口
│   └── main.py              # `python -m src.main "请求"`
│
├── skills/                  # 技能包(独立 pip install)
│   ├── agentvet_pack/       # 示例: AI 安全扫描 (L1-L4)
│   ├── crawler_pack/        # 通用 HTTP 爬虫 (fetch/extract/post)
│   └── ppt_pack/            # ⏳ 占位
│
├── pyproject.toml           # 依赖 + pytest/ruff/mypy 配置
├── .github/workflows/       # CI(test.yml, push 触发)
└── README.md                # 你正在读的
```

---

## 测试

```bash
# 全部
python -m pytest --tb=short -q
# 230 passed

# 只跑单元
python -m pytest tests/unit -q

# 只跑集成
python -m pytest tests/integration -q

# 只跑 e2e
python -m pytest tests/e2e -q

# 看覆盖
python -m pytest --cov=core --cov=layers --cov=stub --cov-report=term-missing
```

---

## 开发进度(15 天)

| Day | 日期 | 内容 | 测试 | 状态 |
|-----|------|------|------|------|
| 1-5 | 2026-06-25 | 11 ABC + 6 层架构 + 借还机制 | 187 | ✅ |
| 6-10 | 2026-06-26 | Gateway 5端点 + SDK + Gradio + SSE | 209 | ✅ |
| 11-13 | 2026-06-26 | 鉴权中间件 + Docker + 输入校验 | 220 | ✅ |
| 14 | 2026-06-27 上午 | Ollama 本地模型 + Skill Pack 激活 | 230 | ✅ |
| 15 | 2026-06-27 下午 | Ollama 接入重构 + 蜂巢精密化(拆 llm_litellm.py + async httpx + dispatch_async + MemoryCfg + Ollama 真推理) | 245+3 | ✅ |

**当前版本: 0.2.0 — 245 passed + 3 skipped 全绿(3 集成为 Ollama HTTP 502 时容错 skip)。**

> 已修项: ~~网关零鉴权~~ ~~SSE内存泄漏~~ ~~Docker缺失~~ ~~active_provider 找不到静默用第一个~~ ~~Ollama 同步阻塞 event loop~~ ~~NO_PROXY 重复 17 行~~
> 待办(Day 16+): 公司化 6 stub 示例化(OAuth/Kafka/Stripe/Tenant/OTel/CircuitBreaker)+ HOW_TO_REPLACE 扩展 7 ABC 覆盖 + GitHub Release v0.2.0。

---

## 文档索引

- [VISION.md](docs/VISION.md) — 1 页产品愿景
- [ARCH.md](docs/ARCH.md) — 6 层架构详解 + 借还机制图
- [INTERFACES.md](docs/INTERFACES.md) — 11 个 ABC 接口契约 + 替换原则
- [HOW_TO_REPLACE.md](docs/HOW_TO_REPLACE.md) — 5 个真实替换场景(Auth→OAuth, Audit→Kafka, ...)
- [CHANGELOG.md](docs/CHANGELOG.md) — 升级日志

---

## 核心承诺

1. **每个文件 ≤ 300 行**(Miku 桌宠规则沿用)
2. **新代码 1 行配 2 行测试**(Miku 桌宠 54 测试的密度)
3. **所有可升级点 = ABC 接口**, 实现 = stub, 换 = 改配置
4. **核心代码 0 修改**就能换 auth/audit/billing/... 任一公司实现

---

## License

MIT
