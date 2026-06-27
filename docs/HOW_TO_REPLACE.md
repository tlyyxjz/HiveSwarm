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
