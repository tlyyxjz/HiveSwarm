"""DefaultTenant — 单租户占位. 换公司 IdP 改 1 行配置."""
from __future__ import annotations

from core.tenant import Tenant, TenantContext


class DefaultTenant(TenantContext):
    """MVP: 只有 default 租户,所有技能都能用."""

    _SINGLETON = Tenant(
        tenant_id="default",
        name="Default",
        plan="pro",
        skill_allowlist=(),  # 空 = 不限
    )

    def get(self, tenant_id: str) -> Tenant:
        if tenant_id != "default":
            # 不存在就当 default 返回,不报错(MVP 友好)
            return self._SINGLETON
        return self._SINGLETON

    def can_use_skill(self, tenant_id: str, skill_name: str) -> bool:
        return True  # MVP 不限
