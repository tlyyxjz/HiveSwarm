# INTERFACES — 11 个 ABC 接口清单

**核心规则**: `core/` 下的 ABC 一旦发布,签名不能改(只能加新方法)。业务层只依赖 ABC,不依赖 stub。改实现 = 加新 stub + 改 config,不碰核心。

---

## 1. core/auth.py — AuthProvider

```python
class AuthProvider(ABC):
    @abstractmethod
    def check_token(self, token: str) -> UserContext: ...

    @abstractmethod
    def whoami(self) -> UserContext: ...
```

**用途**: 验 token → UserContext(user_id, role, tenant_id)
**契约**:
- `check_token` 失败必须抛 `InvalidTokenError`(业务异常)
- `whoami` 是 SDK 内部用,必须返回当前进程身份
- 线程安全
**当前实现**:
- `stub.auth_simple.SimpleAuth` — 永远返回 admin
**可换**:
- `OAuth2Auth` / `JWTAuth` / `mTLSAuth` / `APIKeyAuth`

---

## 2. core/audit.py — AuditLogger

```python
class AuditLogger(ABC):
    @abstractmethod
    def log(self, actor, action, target="", result="ok", metadata=None) -> None: ...

    @abstractmethod
    def query(self, actor=None, action=None, since=None, limit=100) -> list[dict]: ...
```

**用途**: 写审计日志(谁/何时/做了什么)
**契约**:
- 失败**必须**降级到本地缓存,不能阻塞主流程
- append-only,失败不能改写历史
- `query` 返回倒序(最新在前)
**当前实现**: `stub.audit_logfile.LogFileAudit` — 本地 JSONL
**可换**: `KafkaAudit` / `S3Audit` / `BlockchainAudit` / `CloudWatchAudit`

---

## 3. core/billing.py — BillingMeter

```python
class BillingMeter(ABC):
    @abstractmethod
    def record(self, usage: UsageRecord) -> None: ...

    @abstractmethod
    def usage_for(self, user_id: str, period: str = "month") -> int: ...
```

**用途**: 按 token / 任务 / 技能调用次数计量
**契约**:
- `UsageRecord` 是 `@dataclass(frozen=True)`, 可哈希
- 失败**必须**降级本地缓存,后台异步 flush
- `usage_for` 返回金额(分),不是浮点美元
**当前实现**: `stub.billing_noop.NoopBilling` — 啥都不干
**可换**: `StripeBilling` / `AliyunBilling` / `PostgreSQLBilling`

---

## 4. core/tenant.py — TenantContext

```python
class TenantContext(ABC):
    @abstractmethod
    def get(self, tenant_id: str) -> Tenant: ...

    @abstractmethod
    def can_use_skill(self, tenant_id: str, skill_name: str) -> bool: ...
```

**用途**: 多租户隔离 + 技能白名单
**契约**:
- `get` 不存在租户 → 抛 `TenantNotFoundError` 或返回 default(看你策略)
- `can_use_skill` 必须**快**(每任务调 N 次),不允许同步调远端
**当前实现**: `stub.tenant_default.DefaultTenant` — 永远允许
**可换**: `IdpTenant` / `DatabaseTenant` / `JWTTenant`(从 token 解)

---

## 5. core/recovery.py — RecoveryStrategy

```python
class RecoveryStrategy(ABC):
    @abstractmethod
    def guard(self, op, *, max_retries=3, fallback=None) -> T: ...

    @property
    @abstractmethod
    def state(self) -> CircuitState: ...
```

**用途**: 包住"会失败的操作",提供 retry/circuit-breaker/fallback
**契约**:
- `guard` 必须**保证 op 至少跑一次**(包括 fallback 也跑)
- `fallback` 不为 None 时,失败不抛,返回 fallback
- `state` 是同步属性,可被 dashboard 高频轮询
**当前实现**: `stub.recovery_retry.RetryRecovery` — 重试 N 次 + 指数退避
**可换**: `CircuitBreakerRecovery` / `RateLimitedRecovery` / `HystrixStyleRecovery`

---

## 6. core/telemetry.py — Tracer

```python
class Tracer(ABC):
    @contextmanager
    @abstractmethod
    def span(self, name: str, **attrs) -> Iterator[None]: ...

    @abstractmethod
    def metric_inc(self, name: str, value: int = 1, **tags) -> None: ...

    @abstractmethod
    def metric_observe(self, name: str, value_ms: float, **tags) -> None: ...
```

**用途**: 链路追踪 + 计数 + 直方图
**契约**:
- `span` 是 contextmanager, `with` 块结束必须 close(无论异常)
- `metric_*` 失败**不能**阻塞主流程(降级 noop)
- `metric_observe` 单位是毫秒
**当前实现**: `stub.telemetry_noop.NoopTelemetry` — 全 noop
**可换**: `OpenTelemetryTracer` / `DatadogTracer` / `PrometheusTracer`

---

## 7. core/governance.py — DataRetention

```python
class DataRetention(ABC):
    @abstractmethod
    def should_retain(self, record: dict, age_days: int) -> bool: ...

    @abstractmethod
    def scrub_pii(self, text: str) -> str: ...
```

**用途**: 数据保留策略 + PII 脱敏
**契约**:
- `should_retain` 必须**快**(每条记录调)
- `scrub_pii` 失败**必须**降级到原文(不能抛)
- 至少处理:邮箱 / 手机号 / 身份证号
**当前实现**: `stub.governance_permanent.PermanentRetention` — 永久 + 脱敏哨兵
**可换**: `GDPRRetention` / `DLPGovernance` / `CompanyDLP`

---

## 8. core/skill.py — Skill

```python
class Skill(ABC):
    def __init__(self, manifest: SkillManifest) -> None: ...
    @abstractmethod
    def run(self, input_data: dict) -> dict: ...
    async def health_check(self) -> SkillHealth: ...
```

**用途**: 技能契约。所有 skill 必须实现 `run`。
**契约**:
- `run` 输入输出都是 dict(JSON-like)
- `run` 失败抛异常(让 Borrowed 兜住归还)
- `health_check` 默认实现 = 100% 成功率(可 override)
- `manifest` 必填,Pool 看 manifest 调度
**当前实现**: 测试用 `FakeSkill` / 业务用 `agentvet_pack` 里的 `ScanL1Skill` 等
**可换**: 任何第三方工具包(只要填 `SkillManifest` + 实现 `run`)

---

## 9. core/agent.py — Agent

```python
class Agent(ABC):
    agent_id: str
    skills: list[str]

    @abstractmethod
    async def run(self, task: dict) -> dict: ...

    @abstractmethod
    def destroy(self) -> None: ...
```

**用途**: 临时智能体契约。
**契约**:
- `skills` 是**只读**字符串列表(技能名,不是实例)
- `run` 失败必须抛异常(让 Transaction 兜住)
- `destroy` 后**不能再 run**(抛 `AgentAlreadyDestroyedError`)
**当前实现**: `layers.work.factory.TempAgent`
**可换**: 任何继承 ABC 的实现,但要遵守契约

---

## 10. core/brain.py — Brain

```python
class Brain(ABC):
    @abstractmethod
    async def plan(self, request: str, context: dict | None = None) -> Plan: ...

    @abstractmethod
    async def decide(self, plan: Plan, observations: list[dict]) -> tuple[str, str]: ...
```

**用途**: 拆任务 + 失败决策
**契约**:
- `plan` 返回的 `Plan` 至少有 1 个 subtask
- `plan` 失败**必须**降级(不能让请求卡住)
- `decide` 返回 `(action, reason)`,action ∈ {"continue", "switch", "reassemble", "halt"}
**当前实现**: `layers.brain.planner.MockBrain` (无 LLM key) + `LLMBrain` (有 key)
**可换**: `RuleBrain` / `HeuristicBrain` / `LLMBrain` (任意 provider)

---

## 11. core/events.py — EventBus

```python
class EventBus(ABC):
    @abstractmethod
    def publish(self, event: Event) -> None: ...

    @abstractmethod
    def subscribe(self, event_type: EventType, fn: Subscriber) -> None: ...

    @abstractmethod
    def replay(self, since_ts: datetime | None = None) -> list[Event]: ...
```

**用途**: 跨层事件总线
**契约**:
- `publish` **同步**触发所有 subscriber
- subscriber 失败**不能**影响其他 subscriber 或 publish
- `replay` 返回倒序(最新在前)
- `Event` 不可变(`@dataclass(frozen=True)`)
**当前实现**: `stub.bus_local.LocalEventBus` — 进程内 + 内存 log
**可换**: `KafkaEventBus` / `RabbitMQEventBus` / `RedisPubSub`

---

## 12. 辅助 dataclass(在 core/skill.py 和 core/brain.py)

| Dataclass | 字段 | 用途 |
|---|---|---|
| `UserContext` | user_id, role, tenant_id, anonymous | 身份 |
| `UsageRecord` | user_id, skill_name, input_tokens, output_tokens, duration_ms | 计量 |
| `Tenant` | tenant_id, name, plan, skill_allowlist | 租户 |
| `SkillManifest` | name, api_version, min_core_version, description, tags | 技能元数据 |
| `SkillHealth` | name, success/failure_count, error_rate | 技能健康度 |
| `SubTask` | sub_id, intent, required_skills, depends_on, acceptance | 子任务 |
| `Plan` | task_id, original_request, subtasks, rationale | 完整拆解 |
| `Event` | type, payload, ts | 事件 |

这些 dataclass 是**对外契约**的一部分,改字段 = 破坏接口。

---

## 替换指南(简版,完整版见 HOW_TO_REPLACE.md)

### 加一个新 stub 的步骤(以 OAuth 为例)

1. **加文件** `stub/auth_oauth.py`:
   ```python
   from core.auth import AuthProvider, UserContext

   class OAuthAuth(AuthProvider):
       def __init__(self, issuer: str, jwks_url: str) -> None:
           self.issuer = issuer
           self.jwks_url = jwks_url
           # ... 加载 JWKS 缓存

       def check_token(self, token: str) -> UserContext:
           # 验签名 / 查 JWKS / 解析 claim
           ...
           return UserContext(...)

       def whoami(self) -> UserContext:
           # 从环境变量 / 配置文件读 service token
           ...
   ```

2. **加测试** `tests/unit/test_auth_oauth.py`:
   - 验 ABC 签名
   - 验 token 解析
   - 验失败抛 InvalidTokenError

3. **改 config** `config/production.toml`:
   ```toml
   [auth]
   provider = "stub.auth_oauth.OAuthAuth"
   ```

4. **改 Services 加载**(只在 `stub/services.py` 加 1 个分支):
   ```python
   if cfg.auth.provider == "stub.auth_oauth.OAuthAuth":
       auth = OAuthAuth(issuer=..., jwks_url=...)
   ```

5. **跑测试** `pytest tests/unit` — 必须绿

**核心代码 0 修改**。`core/auth.py` 完全没动,业务层完全没感知。

---

## 常见错误

❌ **改 ABC 签名** — 破坏所有实现,升级不兼容
❌ **业务层 import 具体 stub** — 绑死,无法换
❌ **改 dataclass 字段** — 破坏序列化/反序列化
❌ **在 ABC 里加默认实现** — 抽象的"形状"被实现悄悄继承,违反"接口要明确"原则

✅ 改 ABC 只加新方法(不删不改旧)
✅ 业务层永远 `from core.xxx import Xxx` 不用 `from stub.xxx import`
✅ dataclass 加字段用 `field(default=...)` 保证兼容
✅ ABC 用 `@abstractmethod` 强制实现,默认行为放 stub
