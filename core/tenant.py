"""TenantContext — 多租户隔离 ABC.

职责:告诉业务层"当前请求属于哪个租户",数据隔离、配额隔离、技能白
名单隔离. MVP 默认单租户,公司里接公司 IdP 的租户体系.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Tenant:
    """租户."""

    tenant_id: str
    name: str
    plan: str = "free"  # "free" | "pro" | "enterprise"
    skill_allowlist: tuple[str, ...] = ()


class TenantContext(ABC):
    """租户上下文. 通过 UserContext.tenant_id 解析."""

    @abstractmethod
    def get(self, tenant_id: str) -> Tenant:
        """查租户详情."""

    @abstractmethod
    def can_use_skill(self, tenant_id: str, skill_name: str) -> bool:
        """租户能否用这个技能(白名单 + 计划)."""
