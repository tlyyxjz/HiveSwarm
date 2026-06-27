"""接口契约测试 — 验证 stub 真的实现了 ABC.

Day 1 的核心守门: 以后任何人改 stub, 如果签名对不上 ABC 就炸.
"""
from __future__ import annotations

import inspect
from typing import Any

import pytest

from core.agent import Agent
from core.audit import AuditLogger
from core.auth import AuthProvider, UserContext
from core.billing import BillingMeter, UsageRecord
from core.brain import Brain, Plan, SubTask
from core.events import Event, EventBus, EventType
from core.governance import DataRetention
from core.recovery import RecoveryStrategy
from core.skill import Skill, SkillManifest
from core.telemetry import Tracer
from core.tenant import Tenant, TenantContext
from stub.audit_logfile import LogFileAudit
from stub.auth_simple import SimpleAuth
from stub.billing_noop import NoopBilling
from stub.bus_local import LocalEventBus
from stub.governance_permanent import PermanentRetention
from stub.recovery_retry import RetryRecovery
from stub.store_sqlite import SQLiteStore
from stub.telemetry_noop import NoopTelemetry
from stub.tenant_default import DefaultTenant


# ── helpers ──────────────────────────────────────────────────────────────

def _abstract_methods(abc_cls: type) -> set[str]:
    return set(abc_cls.__abstractmethods__)


def _has_all_methods(stub_cls: type, abc_cls: type) -> bool:
    """stub 必须实现 abc 的全部 @abstractmethod."""
    abstract = _abstract_methods(abc_cls)
    defined = set(dir(stub_cls))
    return abstract <= defined


# ── AuthProvider ─────────────────────────────────────────────────────────

class TestAuthProvider:
    def test_stub_implements_abc(self, tmp_path):
        assert _has_all_methods(SimpleAuth, AuthProvider)

    def test_check_token_returns_user_context(self):
        # Empty token → anonymous viewer
        ctx = SimpleAuth().check_token("")
        assert isinstance(ctx, UserContext)
        assert ctx.anonymous is True
        assert ctx.role == "viewer"

    def test_check_token_known_returns_admin(self):
        ctx = SimpleAuth().check_token("mvp-token-admin")
        assert ctx.user_id == "admin_user"
        assert ctx.role == "admin"

    def test_check_token_unknown_raises(self):
        import pytest
        with pytest.raises(Exception):
            SimpleAuth().check_token("bogus-token")

    def test_whoami_works(self):
        assert SimpleAuth().whoami().anonymous is False


# ── AuditLogger ──────────────────────────────────────────────────────────

class TestAuditLogger:
    def test_stub_implements_abc(self, tmp_path):
        assert _has_all_methods(LogFileAudit, AuditLogger)

    def test_log_and_query(self, tmp_path):
        a = LogFileAudit(tmp_path / "a.jsonl")
        a.log("alice", "task.create", target="t1")
        a.log("bob", "task.complete", target="t1", result="ok")
        rows = a.query(limit=10)
        assert len(rows) == 2
        assert rows[0]["actor"] == "alice"
        assert a.query(actor="bob")[0]["action"] == "task.complete"
        a.close()

    def test_query_filter_by_action(self, tmp_path):
        a = LogFileAudit(tmp_path / "a.jsonl")
        a.log("u", "a.x")
        a.log("u", "b.y")
        assert len(a.query(action="a.x")) == 1


# ── BillingMeter ─────────────────────────────────────────────────────────

class TestBillingMeter:
    def test_stub_implements_abc(self):
        assert _has_all_methods(NoopBilling, BillingMeter)

    def test_record_does_not_raise(self):
        NoopBilling().record(UsageRecord(user_id="u", skill_name="s", input_tokens=10))

    def test_usage_returns_int(self):
        assert NoopBilling().usage_for("u") == 0


# ── TenantContext ────────────────────────────────────────────────────────

class TestTenantContext:
    def test_stub_implements_abc(self):
        assert _has_all_methods(DefaultTenant, TenantContext)

    def test_get_default(self):
        t = DefaultTenant().get("default")
        assert isinstance(t, Tenant)
        assert t.tenant_id == "default"

    def test_can_use_skill(self):
        assert DefaultTenant().can_use_skill("default", "any_skill") is True


# ── RecoveryStrategy ─────────────────────────────────────────────────────

class TestRecoveryStrategy:
    def test_stub_implements_abc(self):
        assert _has_all_methods(RetryRecovery, RecoveryStrategy)

    def test_guard_success(self):
        r = RetryRecovery(base_delay_s=0.001)
        assert r.guard(lambda: 42) == 42

    def test_guard_retry_then_success(self):
        r = RetryRecovery(base_delay_s=0.001)
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("nope")
            return "ok"

        assert r.guard(flaky, max_retries=3) == "ok"
        assert calls["n"] == 2

    def test_guard_fallback_on_full_failure(self):
        r = RetryRecovery(base_delay_s=0.001)
        assert r.guard(lambda: (_ for _ in ()).throw(RuntimeError("x")), fallback="def") == "def"


# ── Telemetry ────────────────────────────────────────────────────────────

class TestTelemetry:
    def test_stub_implements_abc(self):
        assert _has_all_methods(NoopTelemetry, Tracer)

    def test_span_context_manager(self):
        t = NoopTelemetry()
        with t.span("op", k="v"):
            pass  # 不抛就是过

    def test_metrics_do_not_raise(self):
        t = NoopTelemetry()
        t.metric_inc("c", 1, tag="x")
        t.metric_observe("h", 12.5, tag="x")


# ── DataRetention ────────────────────────────────────────────────────────

class TestGovernance:
    def test_stub_implements_abc(self):
        assert _has_all_methods(PermanentRetention, DataRetention)

    def test_should_retain_always_true(self):
        assert PermanentRetention().should_retain({}, age_days=99999) is True

    def test_scrub_email(self):
        scrubbed = PermanentRetention().scrub_pii("hi alice@foo.com bye")
        assert "alice@foo.com" not in scrubbed
        assert "[MVP-NO-SCRUB]" in scrubbed


# ── EventBus ─────────────────────────────────────────────────────────────

class TestEventBus:
    def test_stub_implements_abc(self):
        assert _has_all_methods(LocalEventBus, EventBus)

    def test_publish_and_subscribe(self):
        bus = LocalEventBus()
        received: list[Event] = []

        def listener(e: Event) -> None:
            received.append(e)

        bus.subscribe(EventType.TASK_STARTED, listener)
        bus.publish(Event(type=EventType.TASK_STARTED, payload={"x": 1}))
        bus.publish(Event(type=EventType.TASK_COMPLETED, payload={"x": 2}))  # 不订阅,不收
        assert len(received) == 1
        assert received[0].payload == {"x": 1}

    def test_replay(self):
        bus = LocalEventBus()
        bus.publish(Event(type=EventType.TASK_STARTED, payload={"i": 0}))
        bus.publish(Event(type=EventType.TASK_COMPLETED, payload={"i": 1}))
        log = bus.replay()
        assert len(log) == 2


# ── SQLiteStore ──────────────────────────────────────────────────────────

class TestSQLiteStore:
    def test_put_get(self, tmp_path):
        s = SQLiteStore(tmp_path / "m.db")
        s.put("k1", {"v": 1})
        assert s.get("k1") == {"v": 1}

    def test_get_default(self, tmp_path):
        s = SQLiteStore(tmp_path / "m.db")
        assert s.get("nope", default="x") == "x"

    def test_delete(self, tmp_path):
        s = SQLiteStore(tmp_path / "m.db")
        s.put("k", "v")
        s.delete("k")
        assert s.get("k") is None

    def test_list_keys_with_prefix(self, tmp_path):
        s = SQLiteStore(tmp_path / "m.db")
        s.put("user:1", "a")
        s.put("user:2", "b")
        s.put("task:1", "c")
        assert set(s.list_keys("user:")) == {"user:1", "user:2"}


# ── Services 聚合根 ──────────────────────────────────────────────────────

class TestServices:
    def test_build_default_services(self, tmp_path, monkeypatch):
        # 让 build_default_services 用 tmp_path
        import stub.services as svc_mod

        def _patched(config=None):
            return _make_services_in(tmp_path)

        monkeypatch.setattr(svc_mod, "build_default_services", _patched)
        s = svc_mod.build_default_services()
        assert s.auth is not None
        assert s.bus is not None
        assert s.memory is not None
        s.shutdown()  # 不抛


def _make_services_in(tmp_path):
    from stub.audit_logfile import LogFileAudit
    from stub.auth_simple import SimpleAuth
    from stub.billing_noop import NoopBilling
    from stub.bus_local import LocalEventBus
    from stub.dashboard_gradio import GradioDashboard
    from stub.governance_permanent import PermanentRetention
    from stub.recovery_retry import RetryRecovery
    from stub.services import Services
    from stub.store_sqlite import SQLiteStore
    from stub.telemetry_noop import NoopTelemetry
    from stub.tenant_default import DefaultTenant

    return Services(
        auth=SimpleAuth(),
        audit=LogFileAudit(tmp_path / "audit.jsonl"),
        billing=NoopBilling(),
        tenant=DefaultTenant(),
        recovery=RetryRecovery(base_delay_s=0.001),
        telemetry=NoopTelemetry(),
        governance=PermanentRetention(),
        bus=LocalEventBus(),
        memory=SQLiteStore(tmp_path / "memory.db"),
        dashboard=GradioDashboard(),
    )
