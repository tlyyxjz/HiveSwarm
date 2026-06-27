"""pytest 共享 fixture.

约定:
  - tmp_path: 自动临时目录
  - services: 全 stub 的 Services 实例, 用临时路径避免污染
"""
from __future__ import annotations

from pathlib import Path

import pytest

from stub.services import Services, build_default_services


@pytest.fixture
def services(tmp_path: Path) -> Services:
    """构造 Services, 全部写临时目录."""
    # 临时覆盖默认 runtime 路径,避免污染 ~/.hiveswarm
    import stub.services as _svc

    original = _svc.build_default_services

    def _patched(config: str | Path = "config/mvp.toml") -> Services:
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

        return Services(
            auth=SimpleAuth(),
            audit=LogFileAudit(tmp_path / "audit.jsonl"),
            billing=NoopBilling(),
            tenant=DefaultTenant(),
            recovery=RetryRecovery(base_delay_s=0.001),  # 测试用短间隔
            telemetry=NoopTelemetry(),
            governance=PermanentRetention(),
            bus=LocalEventBus(),
            memory=SQLiteStore(tmp_path / "memory.db"),
            dashboard=GradioDashboard(),
        )

    return _patched()
