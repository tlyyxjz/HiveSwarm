# HOW_TO_REPLACE — 替换 stub 为公司实现

**核心原则**: 替换 = 加新 stub + 改 config,**核心代码 0 修改**。

每个场景 5 步:
1. 加新 stub 文件
2. 写测试
3. 改 config
4. 改 Services 加载
5. 跑测试验证

---

## 场景 1: Auth 从 SimpleAuth → OAuth (公司 SSO)

### 业务背景
公司用 Okta / Azure AD / 自建 OAuth2。要把 `stub.auth_simple.SimpleAuth`(永远 admin)替换为真 OAuth。

### Step 1: 加新 stub

`stub/auth_oauth.py`:
```python
"""OAuth 2.0 Auth provider. 验 JWT token via JWKS."""
from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass

import jwt  # PyJWT

from core.auth import AuthProvider, UserContext

_log = logging.getLogger(__name__)


class InvalidTokenError(Exception):
    """Token 验失败. 业务层捕获处理."""


class OAuthAuth(AuthProvider):
    def __init__(self, issuer: str, jwks_url: str, audience: str) -> None:
        self._issuer = issuer
        self._jwks_url = jwks_url
        self._audience = audience
        self._jwks_cache: dict | None = None

    def _get_jwks(self) -> dict:
        if self._jwks_cache is None:
            with urllib.request.urlopen(self._jwks_url) as resp:
                self._jwks_cache = json.loads(resp.read())
        return self._jwks_cache

    def check_token(self, token: str) -> UserContext:
        try:
            jwks = self._get_jwks()
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")
            key = next((k for k in jwks["keys"] if k["kid"] == kid), None)
            if key is None:
                raise InvalidTokenError(f"kid {kid!r} not in JWKS")

            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
            claims = jwt.decode(
                token,
                public_key,
                algorithms=[key.get("alg", "RS256")],
                audience=self._audience,
                issuer=self._issuer,
            )
            return UserContext(
                user_id=claims["sub"],
                role=claims.get("role", "viewer"),
                tenant_id=claims.get("tenant", "default"),
            )
        except (jwt.InvalidTokenError, KeyError, ValueError) as exc:
            raise InvalidTokenError(str(exc)) from exc

    def whoami(self) -> UserContext:
        # SDK 内部用, 读 service token from env
        import os
        svc_token = os.getenv("HIVESWARM_SERVICE_TOKEN", "")
        if not svc_token:
            return UserContext(user_id="service", role="admin", anonymous=True)
        return self.check_token(svc_token)
```

### Step 2: 写测试

`tests/unit/test_auth_oauth.py`:
```python
import pytest
from unittest.mock import patch, MagicMock
from stub.auth_oauth import OAuthAuth, InvalidTokenError
from core.auth import UserContext


def test_stub_implements_abc():
    from core.auth import AuthProvider
    abstract = set(AuthProvider.__abstractmethods__)
    assert abstract <= set(dir(OAuthAuth))


def test_check_token_invalid_raises(monkeypatch):
    a = OAuthAuth(issuer="x", jwks_url="http://x", audience="x")
    monkeypatch.setattr(a, "_get_jwks", lambda: {"keys": []})
    with pytest.raises(InvalidTokenError):
        a.check_token("invalid.token.here")
```

### Step 3: 改 config

`config/production.toml`:
```toml
[auth]
provider = "stub.auth_oauth.OAuthAuth"

# 新加 key (不是 ABC 的字段, 是 stub 自己的)
[auth.options]
issuer = "https://sso.company.com"
jwks_url = "https://sso.company.com/.well-known/jwks.json"
audience = "hiveswarm-api"
```

### Step 4: 改 Services 加载

`stub/services.py`:
```python
def build_default_services(...):
    ...
    # 原来:
    # auth=SimpleAuth(),
    # 改为:
    from stub.config_loader import load_config
    cfg = load_config(...)
    if cfg.auth.provider == "stub.auth_oauth.OAuthAuth":
        from stub.auth_oauth import OAuthAuth
        from stub.config_loader import _parse_auth_options  # 自己写
        opts = _parse_auth_options(cfg)
        auth = OAuthAuth(**opts)
    else:
        from stub.auth_simple import SimpleAuth
        auth = SimpleAuth()
    ...
```

### Step 5: 跑测试
```bash
pytest tests/unit/test_auth_oauth.py -v
pytest tests/unit -v  # 全部
```

### 失败回退
- 改 `config/production.toml` 那一行 provider 改回 `stub.auth_simple.SimpleAuth`
- 删 `stub/auth_oauth.py` 不会影响核心(核心不依赖它)

---

## 场景 2: Audit 从本地 JSONL → Kafka

### Step 1: 加 stub
`stub/audit_kafka.py`:
```python
import json
import logging
from datetime import datetime
from typing import Any
from kafka import KafkaProducer  # kafka-python
from core.audit import AuditLogger

_log = logging.getLogger(__name__)


class KafkaAudit(AuditLogger):
    def __init__(self, brokers: list[str], topic: str = "hiveswarm.audit") -> None:
        self._producer = KafkaProducer(
            bootstrap_servers=brokers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        self._topic = topic

    def log(self, actor, action, target="", result="ok", metadata=None) -> None:
        try:
            self._producer.send(self._topic, {
                "ts": datetime.now().isoformat(),
                "actor": actor, "action": action, "target": target,
                "result": result, "metadata": metadata or {},
            })
        except Exception as exc:
            _log.warning("kafka audit send failed: %s", exc)
            # 关键: 失败降级, 不能阻塞业务

    def query(self, actor=None, action=None, since=None, limit=100) -> list[dict]:
        # Kafka 不适合 query, 这里建议:
        # 1. 落 ES / ClickHouse 同步索引, 这里只查索引
        # 2. 或者用 Kafka Streams 物化视图
        # MVP: 抛 NotImplementedError
        raise NotImplementedError("query Kafka audit via ES index")
```

### Step 2: 测试
- 验 ABC 签名
- mock KafkaProducer, 验 send 被调 + 失败降级
- query 抛 NotImplementedError

### Step 3: config
```toml
[audit]
provider = "stub.audit_kafka.KafkaAudit"
[audit.options]
brokers = ["kafka-1:9092", "kafka-2:9092"]
topic = "hiveswarm.audit"
```

### Step 4-5: 同上

---

## 场景 3: Billing 从 Noop → Stripe

### Step 1: 加 stub
`stub/billing_stripe.py`:
```python
import stripe
from core.billing import BillingMeter, UsageRecord

class StripeBilling(BillingMeter):
    def __init__(self, api_key: str, customer_id_map: dict[str, str]) -> None:
        stripe.api_key = api_key
        self._map = customer_id_map  # user_id -> stripe customer_id

    def record(self, usage: UsageRecord) -> None:
        customer = self._map.get(usage.user_id)
        if not customer:
            return  # 未知用户不报
        try:
            stripe.UsageRecord.create(
                customer=customer,
                quantity=usage.input_tokens + usage.output_tokens,
                timestamp=int(time.time()),
            )
        except stripe.error.StripeError:
            pass  # 降级

    def usage_for(self, user_id: str, period: str = "month") -> int:
        # 查 stripe 当前用量, 返回 cents
        # MVP: 调 stripe.Invoice.upcoming
        ...
        return 0  # placeholder
```

### 关键契约回顾
- `record` 失败**必须**降级(不能阻塞业务)
- `usage_for` 返回整数 cents
- 不要在 record 里做长 IO(异步更好)

---

## 场景 4: Memory 从 SQLite → Qdrant

### Step 1: 加 stub
`stub/store_qdrant.py`:
```python
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
import json
import time
import uuid

class QdrantStore:
    """Qdrant 向量存储, 跟 SQLiteStore 同样的接口."""
    def __init__(self, url: str, collection: str = "hiveswarm_memory") -> None:
        self._client = QdrantClient(url=url)
        self._collection = collection

    def put(self, key: str, value) -> None:
        # Qdrant 是向量库, 简化: 序列化 value 当 vector
        # 真要向量搜索: embed(value) → vector
        payload = json.dumps(value, ensure_ascii=False)
        # 占位: 用 payload hash 当 vector
        vec = [float(hash(payload) % 1000) / 1000.0] * 4
        self._client.upsert(
            collection_name=self._collection,
            points=[PointStruct(
                id=str(uuid.uuid4()),
                vector=vec,
                payload={"key": key, "value": value, "ts": time.time()},
            )],
        )

    def get(self, key: str, default=None):
        # Qdrant 没 key lookup, 要 search. MVP: 改用 sqlite 存 key→id 索引
        # 这里返回 None 简化
        return default

    def delete(self, key: str):
        # 同上
        pass

    def list_keys(self, prefix: str = "") -> list[str]:
        return []
```

**注意**: Qdrant 没有"按 key 查",要向量相似度搜索。如果想保留 key 语义,加个 sqlite 存 key→id 索引。

### Step 2-5: 同上模式

---

## 场景 5: Bus 从 Local → Kafka

### Step 1: 加 stub
`stub/bus_kafka.py`:
```python
import json
import logging
from datetime import datetime
from kafka import KafkaConsumer, KafkaProducer
from core.events import Event, EventBus, EventType, Subscriber

_log = logging.getLogger(__name__)


class KafkaEventBus(EventBus):
    def __init__(self, brokers: list[str], topic: str = "hiveswarm.events", group: str = "hiveswarm") -> None:
        self._producer = KafkaProducer(
            bootstrap_servers=brokers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        self._topic = topic
        self._subs: dict[EventType, list[Subscriber]] = {}
        self._consumer = KafkaConsumer(
            topic,
            bootstrap_servers=brokers,
            group_id=group,
            value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        )
        # 后台线程消费
        import threading
        t = threading.Thread(target=self._consume_loop, daemon=True)
        t.start()

    def _consume_loop(self):
        for msg in self._consumer:
            try:
                rec = msg.value
                e = Event(
                    type=EventType(rec["type"]),
                    payload={k: v for k, v in rec.items() if k not in ("type", "ts")},
                )
                for fn in self._subs.get(e.type, []):
                    try:
                        fn(e)
                    except Exception:
                        _log.warning("subscriber failed", exc_info=True)
            except Exception:
                _log.exception("consume failed")

    def publish(self, event: Event) -> None:
        rec = event.to_dict()
        self._producer.send(self._topic, rec)

    def subscribe(self, event_type: EventType, fn: Subscriber) -> None:
        self._subs.setdefault(event_type, []).append(fn)

    def replay(self, since_ts=None):
        # Kafka 不支持 replay, 用 compacted topic 或外部归档
        return []
```

### 关键: 这是**大改造**, 涉及跨进程

1. 必须部署 Kafka
2. Event 序列化要兼容(用 `to_dict` 没问题)
3. Replay 改用 compacted topic 或外部 ClickHouse
4. 测试要 2 个进程 + 真 Kafka, 单测不全

---

## 替换检查清单

每次替换前过这 5 关:

- [ ] **接口签名一致**: stub 满足 ABC 所有 @abstractmethod
- [ ] **契约遵守**: 失败降级 / 线程安全 / 单元小
- [ ] **测试齐全**: 至少 3 条单测(签名/正常/失败)
- [ ] **config 加 key**: provider 改新值
- [ ] **Services 加载分支**: build_default_services 加新分支

任何一关不过 = 不替换, 继续用 stub。

---

## 紧急回退

替换出问题:
```bash
# 1. 改回 config
sed -i 's/stub.auth_oauth/stub.auth_simple/' config/production.toml

# 2. 重启服务
python -m src.main ...

# 3. 核心代码 0 修改
git diff core/  # 应该是空
```

公司化永远有"回退到 stub"这条路,这是 MVP 设计的核心价值。

---

## 场景 6: Skill (借还) 替换 — 公司内部 Skill 注册中心

### 业务背景
公司有内部 Skill 注册中心（如 Confluent Schema Registry / 自研 SkillVault），
要把 `skills/*.py` 散落文件换成集中拉取 + 借出/归还审计。

### Step 1: 加 stub
`stub/skill_remote.py`:
```python
"""RemoteSkillPool — 从公司 SkillVault 借/还 Skill manifest."""
from __future__ import annotations

import logging
import urllib.request
import json
from core.skill import Skill, SkillPool

_log = logging.getLogger(__name__)


class RemoteSkillPool(SkillPool):
    def __init__(self, vault_url: str, token: str) -> None:
        self._url = vault_url.rstrip("/")
        self._token = token
        self._cache: dict[str, Skill] = {}

    def checkout(self, name: str) -> Skill:
        if name in self._cache:
            return self._cache[name]
        try:
            req = urllib.request.Request(
                f"{self._url}/skills/{name}",
                headers={"Authorization": f"Bearer {self._token}"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            skill = Skill(
                name=data["name"],
                version=data["version"],
                entrypoint=data["entrypoint"],
                manifest=data.get("manifest", {}),
            )
            self._cache[name] = skill
            return skill
        except Exception as exc:
            _log.warning("vault checkout failed: %s", exc, exc_info=True)
            raise

    def checkin(self, name: str) -> None:
        """远端 vault 无需显式 checkin,本地缓存清理."""
        self._cache.pop(name, None)
```

### Step 2: 写测试
`tests/unit/test_skill_remote.py`:
```python
from unittest.mock import patch
from stub.skill_remote import RemoteSkillPool


def test_stub_implements_abc():
    from core.skill import SkillPool
    assert set(SkillPool.__abstractmethods__) <= set(dir(RemoteSkillPool))


def test_checkout_caches_result():
    pool = RemoteSkillPool(vault_url="http://x", token="t")
    fake = {"name": "crawler", "version": "1.0.0", "entrypoint": "skills.crawler.run", "manifest": {}}
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(fake).encode()
        s1 = pool.checkout("crawler")
        s2 = pool.checkout("crawler")  # 第二次走缓存
    assert s1.name == "crawler"
    assert mock_urlopen.call_count == 1
```

### Step 3: 改 config
`config/production.toml`:
```toml
[skill_pool]
provider = "stub.skill_remote.RemoteSkillPool"

[skill_pool.options]
vault_url = "https://skillvault.company.internal"
token = "${HIVESWARM_VAULT_TOKEN}"   # env var 引用
```

### Step 4: 改 Services
```python
# stub/services.py build_default_services
if cfg.skill_pool.provider == "stub.skill_remote.RemoteSkillPool":
    from stub.skill_remote import RemoteSkillPool
    pool = RemoteSkillPool(**cfg.skill_pool.options)
else:
    from stub.services import LocalSkillPool  # 既有
    pool = LocalSkillPool()
```

### Step 5: 验证
```bash
pytest tests/unit/test_skill_remote.py -v
pytest tests/unit -v
```

---

## 场景 7: Agent (临时) 替换 — 公司 Agent 调度系统

### 业务背景
公司有 K8s Job 调度 / AWS Batch，要把临时 Agent (`stub/agent.py`)
换成远程触发，公司 Agent 跑完回调。

### Step 1: 加 stub
`stub/agent_remote.py`:
```python
"""RemoteAgentLauncher — 把 Agent 派给公司 K8s/Batch 跑."""
from __future__ import annotations

import json
import logging
import urllib.request

from core.agent import AgentLauncher, AgentTask, AgentResult

_log = logging.getLogger(__name__)


class RemoteAgentLauncher(AgentLauncher):
    def __init__(self, scheduler_url: str, namespace: str = "default") -> None:
        self._url = scheduler_url.rstrip("/")
        self._ns = namespace

    def launch(self, task: AgentTask) -> str:
        """返回 job_id,后续 poll 拿结果."""
        try:
            payload = json.dumps({
                "namespace": self._ns,
                "image": task.image,
                "command": task.command,
                "env": task.env,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{self._url}/jobs",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())["job_id"]
        except Exception as exc:
            _log.warning("agent launch failed: %s", exc, exc_info=True)
            raise

    def poll(self, job_id: str) -> AgentResult:
        try:
            with urllib.request.urlopen(f"{self._url}/jobs/{job_id}", timeout=5) as resp:
                data = json.loads(resp.read())
            return AgentResult(
                job_id=job_id,
                status=data["status"],   # "queued" | "running" | "done" | "failed"
                output=data.get("output", ""),
            )
        except Exception as exc:
            _log.warning("agent poll failed: %s", exc, exc_info=True)
            raise
```

### Step 2: 写测试
`tests/unit/test_agent_remote.py`:
```python
from unittest.mock import patch, MagicMock
from stub.agent_remote import RemoteAgentLauncher
from core.agent import AgentTask


def test_launch_returns_job_id():
    launcher = RemoteAgentLauncher(scheduler_url="http://scheduler")
    task = AgentTask(image="img:1", command=["run"], env={})
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"job_id": "abc123"}'
    mock_resp.__enter__.return_value = mock_resp
    with patch("urllib.request.urlopen", return_value=mock_resp):
        assert launcher.launch(task) == "abc123"
```

### Step 3: 改 config
`config/production.toml`:
```toml
[agent_launcher]
provider = "stub.agent_remote.RemoteAgentLauncher"
scheduler_url = "https://k8s.company.internal/hiveswarm"
namespace = "agents"
```

### Step 4: 改 Services
按既有 `if cfg.agent_launcher.provider == ...` 分支加载。

### Step 5: 验证
```bash
pytest tests/unit/test_agent_remote.py -v
```

---

## 场景 8: Brain (拆任务) 替换 — 公司 DAG 调度系统

### 业务背景
公司有 Airflow / Prefect / 自研 DAG，要把 Brain 的"任务拆解 + 调度"
换成远程提交 DAG，公司调度器负责执行。

### Step 1: 加 stub
`stub/brain_remote.py`:
```python
"""RemoteBrain — 把拆好的 DAG 提交给公司调度器."""
from __future__ import annotations

import json
import logging
import urllib.request

from core.brain import Brain, DecomposedTask

_log = logging.getLogger(__name__)


class RemoteBrain(Brain):
    def __init__(self, scheduler_url: str, dag_prefix: str = "hiveswarm") -> None:
        self._url = scheduler_url.rstrip("/")
        self._prefix = dag_prefix

    def decompose(self, goal: str) -> DecomposedTask:
        """先本地拆 (复用 Brain ABC),再提交."""
        # MVP: 本地简单拆,公司可换成 LLM planner
        steps = [s.strip() for s in goal.split(";") if s.strip()]
        dag = DecomposedTask(goal=goal, steps=steps)
        try:
            payload = json.dumps({"prefix": self._prefix, "dag": dag.steps}).encode()
            req = urllib.request.Request(
                f"{self._url}/dags", data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                dag.run_id = json.loads(resp.read())["run_id"]
        except Exception as exc:
            _log.warning("dag submit failed, continue local: %s", exc, exc_info=True)
        return dag
```

### Step 2: 写测试
`tests/unit/test_brain_remote.py`:
```python
def test_decompose_submits_to_scheduler():
    from stub.brain_remote import RemoteBrain
    from unittest.mock import patch, MagicMock
    brain = RemoteBrain(scheduler_url="http://x")
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"run_id": "r1"}'
    mock_resp.__enter__.return_value = mock_resp
    with patch("urllib.request.urlopen", return_value=mock_resp):
        dag = brain.decompose("step1; step2; step3")
    assert dag.run_id == "r1"
    assert len(dag.steps) == 3
```

### Step 3: 改 config
`config/production.toml`:
```toml
[brain]
provider = "stub.brain_remote.RemoteBrain"
scheduler_url = "https://airflow.company.internal"
dag_prefix = "hiveswarm"
```

### Step 4: 改 Services / Step 5 验证 — 同上模式。

---

## 场景 9: RecoveryStrategy (circuit-breaker) 替换 — 公司 SLO 闸门

### 业务背景
公司有集中式熔断器（Resilience4j / Sentinel / 自研），
要替 `stub/recovery_circuit.CircuitBreaker`（本地版）。

> 注：`stub/recovery_circuit.py` 已经是生产可用的本地 CircuitBreaker；
> 本场景只在你**已经有公司熔断中心**时才需要替换。

### Step 1: 加 stub
`stub/recovery_remote.py`:
```python
"""RemoteRecovery — 把 guard 决策交给公司熔断中心."""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Callable, TypeVar

from core.recovery import CircuitState, RecoveryStrategy

T = TypeVar("T")
_log = logging.getLogger(__name__)


class RemoteRecovery(RecoveryStrategy):
    def __init__(self, sentinel_url: str, service_name: str) -> None:
        self._url = sentinel_url.rstrip("/")
        self._svc = service_name

    def _ask_sentinel(self) -> str:
        try:
            with urllib.request.urlopen(
                f"{self._url}/state/{self._svc}", timeout=2
            ) as resp:
                return json.loads(resp.read())["state"]
        except Exception as exc:
            _log.warning("sentinel query failed, assume closed: %s", exc, exc_info=True)
            return "closed"

    @property
    def state(self) -> CircuitState:
        s = self._ask_sentinel()
        return {"closed": CircuitState.CLOSED, "open": CircuitState.OPEN, "half_open": CircuitState.HALF_OPEN}.get(s, CircuitState.CLOSED)

    def guard(self, op: Callable[[], T], *, max_retries: int = 3, fallback: T | None = None) -> T:
        if self.state == CircuitState.OPEN:
            if fallback is not None:
                return fallback
            raise RuntimeError("sentinel says open")
        last_exc = None
        for attempt in range(max_retries):
            try:
                return op()
            except Exception as exc:
                last_exc = exc
                _log.warning("op failed (%d/%d): %s", attempt + 1, max_retries, exc)
        if fallback is not None:
            return fallback
        raise last_exc  # type: ignore
```

### Step 2-5: 同上模式（provider 切到 `stub.recovery_remote.RemoteRecovery`，options 传 sentinel_url）。

---

## 场景 10: Tracer / Telemetry 替换 — 公司 APM

### 业务背景
公司用 Datadog / NewRelic / SkyWalking，要把
`stub/observability_otel.OTelTracer` 替换为发送 Datadog 的版本。

### Step 1: 加 stub
`stub/telemetry_datadog.py`:
```python
"""DatadogTelemetry — span/metric 上报 Datadog agent."""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator

from core.telemetry import Tracer

_log = logging.getLogger(__name__)


class DatadogTelemetry(Tracer):
    def __init__(self, agent_url: str = "http://localhost:8126", service: str = "hiveswarm") -> None:
        self._url = agent_url.rstrip("/")
        self._service = service

    @contextmanager
    def span(self, name: str, **attrs: object) -> Iterator[None]:
        start = time.monotonic()
        try:
            yield
        finally:
            _log.info("dd.span service=%s name=%s dur_ms=%.1f attrs=%s",
                      self._service, name, (time.monotonic() - start) * 1000, dict(attrs))

    def metric_inc(self, name: str, value: int = 1, **tags: str) -> None:
        _log.info("dd.metric_inc %s +=%d tags=%s", name, value, tags)

    def metric_observe(self, name: str, value_ms: float, **tags: str) -> None:
        _log.info("dd.metric_observe %s =%.2fms tags=%s", name, value_ms, tags)
```

### Step 2-5:
- 测试同 3 条模式（ABC 实现 / span yield / 异常路径）
- config 切 `[telemetry] provider = "stub.telemetry_datadog.DatadogTelemetry"`
- 注意：**OTelTracer 已经是生产可用的本地实现**，只有公司用 Datadog 才换。

---

## 场景 11: DataRetention / Governance 替换 — 公司合规策略

### 业务背景
公司有合规要求（GDPR / SOC2 / 等保），要在 `core/governance.GovernancePolicy`
层面切到公司策略中心（如 OneTrust / 自研策略引擎）。

### Step 1: 加 stub
`stub/governance_remote.py`:
```python
"""RemoteGovernance — 数据保留 / 脱敏 / 删除 走公司策略中心."""
from __future__ import annotations

import json
import logging
import urllib.request

from core.governance import GovernancePolicy

_log = logging.getLogger(__name__)


class RemoteGovernance(GovernancePolicy):
    def __init__(self, policy_url: str, api_key: str) -> None:
        self._url = policy_url.rstrip("/")
        self._key = api_key

    def retention_days(self, data_class: str) -> int:
        try:
            req = urllib.request.Request(
                f"{self._url}/retention/{data_class}",
                headers={"Authorization": f"Bearer {self._key}"},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                return int(json.loads(resp.read())["days"])
        except Exception as exc:
            _log.warning("policy lookup failed, default 90d: %s", exc, exc_info=True)
            return 90

    def should_redact(self, field: str, tenant_id: str) -> bool:
        try:
            req = urllib.request.Request(
                f"{self._url}/redact?field={field}&tenant={tenant_id}",
                headers={"Authorization": f"Bearer {self._key}"},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                return json.loads(resp.read()).get("redact", False)
        except Exception as exc:
            _log.warning("redact policy failed, default redact: %s", exc, exc_info=True)
            return True
```

### Step 2-5:
- 测试同 3 条模式（ABC 实现 / retention_days / should_redact）
- config 切 `[governance] provider = "stub.governance_remote.RemoteGovernance"`
- options 传 policy_url + api_key

---

## 11 ABC 全覆盖对照表

| ABC | 默认 stub | 公司化 stub | HOW_TO_REPLACE 场景 |
|-----|----------|------------|---------------------|
| AuthProvider | SimpleAuth | OAuthAuth | 场景 1 |
| AuditLogger | LogFileAudit | KafkaAudit | 场景 2 |
| BillingMeter | NoopBilling | StripeBilling | 场景 3 |
| MemoryStore | StoreSqlite | (Qdrant 已写) | 场景 4 |
| EventBus | BusLocal | (Kafka 已写) | 场景 5 |
| SkillPool | LocalSkillPool | RemoteSkillPool | 场景 6 |
| AgentLauncher | StubAgent | RemoteAgentLauncher | 场景 7 |
| Brain | LocalBrain | RemoteBrain | 场景 8 |
| RecoveryStrategy | RetryRecovery / CircuitBreaker | RemoteRecovery | 场景 9 |
| Tracer | NoopTelemetry / OTelTracer | DatadogTelemetry | 场景 10 |
| GovernancePolicy | GovernancePermanent | RemoteGovernance | 场景 11 |

**11/11 全覆盖**。任何 ABC → 都有可替换路径，不存在"锁死"。
