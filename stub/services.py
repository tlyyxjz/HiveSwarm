"""Services — 所有 stub 的聚合根. 跟 Miku AppServices 同款套路.

用法:
    from stub.services import build_default_services
    services = build_default_services(config="config/mvp.toml")
    user = services.auth.check_token("xxx")     # 调 auth
    services.bus.publish(...)                   # 调 bus
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.auth import AuthProvider
from core.audit import AuditLogger
from core.billing import BillingMeter
from core.events import EventBus
from core.governance import DataRetention
from core.recovery import RecoveryStrategy
from core.telemetry import Tracer
from core.tenant import TenantContext
from stub.audit_logfile import LogFileAudit
from stub.auth_simple import SimpleAuth
from stub.billing_noop import NoopBilling
from stub.bus_local import LocalEventBus
from stub.dashboard_gradio import GradioDashboard
from stub.governance_permanent import PermanentRetention
from stub.recovery_retry import RetryRecovery
from stub.store_sqlite import SQLiteStore
from stub.telemetry_noop import NoopTelemetry
from stub.tenant_default import DefaultTenant


@dataclass
class Services:
    """MVP 全 stub 聚合根. 跟 Miku 桌宠的 AppServices 一致套路."""

    auth: AuthProvider
    audit: AuditLogger
    billing: BillingMeter
    tenant: TenantContext
    recovery: RecoveryStrategy
    telemetry: Tracer
    governance: DataRetention
    bus: EventBus
    memory: SQLiteStore
    dashboard: GradioDashboard

    def shutdown(self) -> None:
        """统一关闭. 跟 AppServices.shutdown() 同套路."""
        # close 资源(每个 try,别一个坏拖累其他)
        for closer in (
            getattr(self.audit, "close", None),
        ):
            if closer is not None:
                try:
                    closer()
                except Exception:
                    pass


def build_default_services(
    config: str | Path = "config/mvp.toml",
) -> Services:
    """构造全 stub 的 Services. 后续会读 toml 走动态加载."""
    config_path = Path(config)
    # MVP 直接给默认值,Day 2 才读 toml
    runtime_dir = Path("~/.hiveswarm").expanduser()
    return Services(
        auth=SimpleAuth(),
        audit=LogFileAudit(runtime_dir / "logs/audit.jsonl"),
        billing=NoopBilling(),
        tenant=DefaultTenant(),
        recovery=RetryRecovery(),
        telemetry=NoopTelemetry(),
        governance=PermanentRetention(),
        bus=LocalEventBus(),
        memory=SQLiteStore(runtime_dir / "memory.db"),
        dashboard=GradioDashboard(),
    )
