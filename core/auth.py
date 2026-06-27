"""AuthProvider — 身份认证 / 授权 ABC.

职责:验证 token → UserContext. 业务层(Brain/Work)通过 UserContext 判断
"这个任务谁来跑、能不能跑". MVP 永远返回 admin,公司里换 OAuth/JWT.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class UserContext:
    """调用方身份. 不可变,线程安全."""

    user_id: str
    role: str  # "admin" | "developer" | "viewer"
    tenant_id: str = "default"
    anonymous: bool = False


class AuthProvider(ABC):
    """身份提供方. 实现可以是 SimpleAuth(永远 admin)/ OAuth / JWT / mTLS."""

    @abstractmethod
    def check_token(self, token: str) -> UserContext:
        """验 token 返回身份. 失败抛 InvalidTokenError."""

    @abstractmethod
    def whoami(self) -> UserContext:
        """当前进程身份(SDK 内部用)."""
