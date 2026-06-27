"""Tests for stub.tenant_multi.MultiTenant.

验租户隔离: A 不可读 B / 切换租户 / 跨租户抛 PermissionError.
"""
from __future__ import annotations

import pytest

from stub.tenant_multi import MultiTenant


@pytest.fixture
def tenants() -> MultiTenant:
    return MultiTenant(
        {
            "acme": {"name": "Acme", "plan": "enterprise", "skill_allowlist": ["crawler"]},
            "globex": {"name": "Globex", "plan": "free", "skill_allowlist": []},
        }
    )


def test_get_existing_tenant(tenants):
    t = tenants.get("acme")
    assert t.tenant_id == "acme"
    assert t.name == "Acme"
    assert t.plan == "enterprise"
    assert t.skill_allowlist == ("crawler",)


def test_get_unknown_tenant_raises_permission_error(tenants):
    """不存在租户 → PermissionError (区别于 default 兜底)."""
    with pytest.raises(PermissionError, match="not found"):
        tenants.get("ghost")


def test_can_use_skill_with_allowlist(tenants):
    """acme 的 allowlist 只有 crawler → 用 ppt 应拒绝."""
    assert tenants.can_use_skill("acme", "crawler") is True
    assert tenants.can_use_skill("acme", "ppt") is False


def test_can_use_skill_empty_allowlist_allows_all(tenants):
    """globex allowlist 为空 → 全部允许."""
    assert tenants.can_use_skill("globex", "anything") is True


def test_cross_tenant_access_denied(tenants):
    """跨租户访问抛 PermissionError."""
    with pytest.raises(PermissionError, match="cross-tenant"):
        tenants.assert_cross_tenant_access("acme", "globex")


def test_same_tenant_access_allowed(tenants):
    """同租户不抛."""
    tenants.assert_cross_tenant_access("acme", "acme")


def test_list_tenants_sorted(tenants):
    assert tenants.list_tenants() == ["acme", "globex"]


def test_concurrent_get_thread_safe(tenants):
    """并发 get 不出错 (Lock 保护)."""
    import threading

    errors: list[Exception] = []

    def worker() -> None:
        try:
            for _ in range(50):
                tenants.get("acme")
                tenants.get("globex")
                tenants.can_use_skill("acme", "crawler")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []