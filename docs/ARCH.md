# ARCH — HiveSwarm 架构详解

## 1. 全局视角

```
┌────────────────────────────────────────────────────────────────┐
│                          用户 (CLI / SDK)                       │
└────────────────────────────────────────────────────────────────┘
                              ↓ 请求
┌────────────────────────────────────────────────────────────────┐
│  Brain (大脑) — 拆任务 + 决策                                   │
│  - LLMBrain / MockBrain                                        │
│  - 输出: Plan (DAG of SubTask)                                 │
└────────────────────────────────────────────────────────────────┘
                              ↓ Plan
┌────────────────────────────────────────────────────────────────┐
│  Work (工作) — 借/装/跑/还/事务                                 │
│  - Pool.checkout(skills) → Bundle                              │
│  - Factory.assemble → TempAgent                                │
│  - Agent.run(task) → result                                    │
│  - Borrowed context manager → auto return                      │
│  - TaskTransaction 编排多 subtask                              │
└────────────────────────────────────────────────────────────────┘
                              ↓ result
┌────────────────────────────────────────────────────────────────┐
│  Inspect (检查) — 硬规则 + LLM Judge                            │
│  - Validator (单条规则) → ValidationResult                     │
│  - Checker (组合多个) → CheckReport                            │
│  - LLMJudge (软评分, 可降级到规则)                             │
└────────────────────────────────────────────────────────────────┘
                              ↓ report (ok/fail)
┌────────────────────────────────────────────────────────────────┐
│  Repair (修补) — 失败重调度                                    │
│  - StrategyTable: 错误关键词 → 动作                            │
│  - Fixer.propose → FixPlan                                     │
│  - ReAssembler: 改 SubTask                                     │
└────────────────────────────────────────────────────────────────┘
                              ↓ 修补后 SubTask
                          (回 Work 重跑)
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  Monitor (监察) — 事件流 + 健康度                               │
│  - EventBus (Local / Kafka)                                    │
│  - EventLogger (JSONL append-only)                             │
│  - HealthSnapshotter (聚合指标)                                │
└────────────────────────────────────────────────────────────────┘
                              ↓ 副作用
┌────────────────────────────────────────────────────────────────┐
│  Memory (记忆) — 3 层存储 + 回忆                                │
│  - short (session) / working (task) / long (跨 session)         │
│  - recall: by_key / by_prefix / by_ts                          │
└────────────────────────────────────────────────────────────────┘
```

## 2. 借还核心机制(创新点)

### 2.1 为什么这样设计

**AutoGen / CrewAI 的问题**:
```python
agent = Agent(tools=[tool1, tool2, tool3, ...])  # 永久绑定
agent.run()  # 跑完也不释放
# 100 个任务 = 100 个长寿命 Agent = OOM
```

**HiveSwarm 的方案**:
```python
# 任务来
bundle = pool.checkout(["tool1", "tool2"])  # 借, 引用计数 +1
try:
    with Borrowed(bundle, pool):  # 事务保证异常也还
        agent = TempAgent(skills=bundle.skills)  # 临时装配
        result = agent.run(task)
        # 任务跑完
        agent.destroy()  # 销毁
# with 退出 → pool.return_back(bundle)  # 还, 引用计数 -1
# 100 个任务 = 100 个借/还循环 = 0 累积
```

### 2.2 关键不变量

1. **借还原子性**: 多个 skill 一起借, 全部成功才 +1; 任一失败全回滚
2. **异常必还**: Borrowed context manager 保证 `with` 块异常也归还
3. **二次还幂等**: Borrowed 重复 `__exit__` 当 noop, 防止双层清理炸
4. **Agent 一次性**: 销毁后 `run()` 抛 `AgentAlreadyDestroyedError`

### 2.3 引用计数细节

```python
pool._refcount: dict[str, int]  # skill_name → 借出次数

checkout(["a", "b"]):  # 全成功
    refcount["a"] += 1  # 1
    refcount["b"] += 1  # 1

return_back(bundle):
    for s in bundle.skills:
        refcount[s] -= 1  # 0

# 并发安全: threading.Lock 保护 dict
# 单 skill 上限: max_concurrent_per_skill=100 (防 DDoS)
```

## 3. 6 层数据流(完整版)

### 3.1 正常路径

```
[用户] "帮我做一个 PPT"
  ↓
[Brain.plan]  Plan(task_id="ppt-001", subtasks=[
    SubTask("s1", "采数据", skills=["data_collect"]),
    SubTask("s2", "写大纲", skills=["outline"], depends_on=["s1"]),
    SubTask("s3", "排版", skills=["layout"], depends_on=["s2"]),
    SubTask("s4", "导出", skills=["export"], depends_on=["s3"]),
  ])
  ↓
[Work] with TaskTransaction(pool, factory, "ppt-001") as tx:
    tx.add(s1).run({"topic": "PPT"})  → 借 data_collect → 装 → 跑 → 还
    tx.add(s2).run({...})              → 借 outline     → 装 → 跑 → 还
    tx.add(s3).run({...})              → 借 layout      → 装 → 跑 → 还
    tx.add(s4).run({...})              → 借 export      → 装 → 跑 → 还
  # 4/4 成功
  ↓
[Inspect] ppt_result_checker.check(last_result)
  → {ok: True, errors: []}
  ↓
[Memory] put(LONG, "task:ppt-001", {all_ok, results, ...})
  ↓
[Monitor] 8 个事件写入 JSONL
  - 4 × SKILL_CHECKED_OUT
  - 4 × SKILL_RETURNED
  - 1 × TASK_COMPLETED
```

### 3.2 失败路径(含修补)

```
[Work] tx.add(s2).run() → skill 抛异常
  → SubTaskResult(ok=False, error="outline crashed")
  ↓
[Transaction] abort=True → 后续 subtask 跳过, 全还
  ↓
[Inspect] checker.check(failed_result) → ok=False
  ↓
[Repair] Fixer.propose(s2, report):
  error 含 "crashed" → 走 re_assemble (fallback)
  → FixPlan(action="re_assemble", new_intent="换种思路写大纲")
  ↓
[ReAssembler] reassemble(s2, plan) → 新 SubTask
  ↓ (可选)
[Brain.decide] 决定是否 halt 或 重新跑
  ↓
[Monitor] 记录 REPAIR_TRIGGERED 事件
```

## 4. 接口稳定性契约

### 4.1 11 个 ABC 都不能动

`core/` 下的 11 个 ABC 文件定义了**所有业务层依赖的接口**。改它们 = 改核心 = 破坏升级性。

```python
# core/skill.py — 技能契约
class Skill(ABC):
    def run(self, input_data: dict) -> dict: ...
    async def health_check(self) -> SkillHealth: ...

# core/skill_bundle.py — 借还契约
class SkillBundle: ...
class Borrowed(AbstractContextManager): ...

# core/agent.py — 临时 Agent 契约
class Agent(ABC):
    async def run(self, task: dict) -> dict: ...
    def destroy(self) -> None: ...
```

### 4.2 替换原则

公司化要换 auth/audit/billing/... 时, **只动 `stub/` 目录**, 加新实现, 改 `config/*.toml` 1 行。

| 公司需求 | 改哪 | 改几行 |
|---|---|---|
| 接 OAuth | 加 `stub/auth_oauth.py` + 改 `config/production.toml` | 1 改 1 加 |
| 接 Kafka 审计 | 加 `stub/audit_kafka.py` + 改 config | 1 改 1 加 |
| 接 Stripe 计费 | 加 `stub/billing_stripe.py` + 改 config | 1 改 1 加 |
| 换 Qdrant 记忆 | 加 `stub/store_qdrant.py` + 改 config | 1 改 1 加 |
| 换 OpenTelemetry | 加 `stub/telemetry_otel.py` + 改 config | 1 改 1 加 |

**核心代码 0 修改**。详见 `docs/HOW_TO_REPLACE.md`(待写)。

## 5. 测试金字塔

```
       E2E (3 条) — 6 层全链, < 5s
      /         \
    Integration  (8 条) — 2-3 层, < 1s
   /              \
  Unit (171 条)  — 单文件纯函数, < 0.5s
```

| 类别 | 文件 | 条数 |
|---|---|---|
| Unit | test_interfaces / test_config_loader / test_skill_bundle / test_pool / test_factory / test_transaction / test_brain / test_inspect / test_repair / test_monitor / test_memory / test_main | 171 |
| Integration | test_work_e2e / test_brain_work_e2e | 8 |
| E2E | test_full_hiveswarm | 3 |
| **总计** | | **182** |

总耗时 **1.20s**,开发循环不卡。

## 6. 性能/扩展性

### 6.1 已知瓶颈

- `asyncio.run` 在 Transaction 每次跑 subtask 时新建 event loop — 真生产应用同一 loop
- 串行 subtask — 没并行,后改 `asyncio.gather`
- 内存 store 用 SQLite — 适合 MVP,公司换 Qdrant/Redis

### 6.2 锁粒度

- `Pool` 整个 dict 一把锁, 简单但中等并发
- 高并发场景换 `dict[str, AtomicInt]` 或 per-skill lock

### 6.3 事件流

- 当前 LocalEventBus 进程内,单机 OK
- 换 Kafka/RabbitMQ = 加 `stub/bus_kafka.py`, 改 1 行 config

## 7. 6 层间的依赖关系(避免循环)

```
Brain ──→ (无依赖,纯函数)
Work ──→ SkillPool, SkillBundle, Brain.SubTask
Inspect ──→ 无 (纯函数)
Repair ──→ Inspect.CheckReport, Brain.SubTask
Monitor ──→ EventBus (注入,不依赖)
Memory ──→ 任意存储后端
```

**关键**: Brain 和 Inspect **不依赖 Work**,所以可以独立测试;Work 不知道有 Repair,Repair 是"事后调用"。

## 8. 下一步演进(Day 6+)

- **Day 6-8**: Gradio 战情看板(5 面板) + 时间旅行回放按钮 + pause point 通知
- **Day 9-10**: FastAPI 网关 + Python SDK(3 个方法)
- **Day 11-12**: 完整文档 + Docker
