"""MultiTenant stub — 多租户隔离,Lock 保护共享缓存.

生产替换: stub.tenant_default.DefaultTenant → stub.tenant_multi.MultiTenant.
        租户数据来源: 配置文件 / 公司 IdP / 数据库.

设计:
    - 租户数据加载后不可变 (frozen dataclass)
    - 共享 dict (self._cache) 用 Lock 保护 (并发 Get 安全)
    - 跨租户访问抛 PermissionError
"""
from __future__ import annotations

import logging
import threading
from typing import Mapping

from core.tenant import Tenant, TenantContext

_log = logging.getLogger(__name__)


class MultiTenant(TenantContext):
    """多租户管理. 启动时从 dict 加载租户元数据.

    Args:
        tenants: tenant_id → 配置 dict 映射
                 {"acme": {"name": "Acme Corp", "plan": "enterprise",
                           "skill_allowlist": ["agentvet", "crawler"]}}
    """

    def __init__(self, tenants: Mapping[str, Mapping[str, object]]) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, Tenant] = {}
        for tid, cfg in tenants.items():
            self._cache[tid] = Tenant(
                tenant_id=str(tid),
                name=str(cfg.get("name", tid)),
                plan=str(cfg.get("plan", "free")),
                skill_allowlist=tuple(cfg.get("skill_allowlist", ()) or ()),
            )

    def get(self, tenant_id: str) -> Tenant:
        """查租户. 不存在抛 PermissionError (区别于 default 兜底)."""
        with self._lock:
            tenant = self._cache.get(tenant_id)
        if tenant is None:
            raise PermissionError(f"tenant {tenant_id!r} not found")
        return tenant

    def can_use_skill(self, tenant_id: str, skill_name: str) -> bool:
        """租户是否被授权使用 skill. 空 allowlist = 全部允许."""
        try:
            tenant = self.get(tenant_id)
        except PermissionError:
            return False
        if not tenant.skill_allowlist:
            return True
        return skill_name in tenant.skill_allowlist

    def assert_cross_tenant_access(self, requester_tenant: str, target_tenant: str) -> None:
        """跨租户访问检查. 防御性: 拒绝一切跨租户读写."""
        if requester_tenant != target_tenant:
            raise PermissionError(
                f"cross-tenant access denied: {requester_tenant!r} → {target_tenant!r}"
            )

    def list_tenants(self) -> list[str]:
        """列所有 tenant_id (debug / admin 用)."""
        with self._lock:
            return sorted(self._cache.keys())