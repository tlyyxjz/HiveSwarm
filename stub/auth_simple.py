"""SimpleAuth — Bearer Token 字典 + 匿名 fallback.

生产换 OAuth/JWT 时,继承 AuthProvider 重写 check_token 即可.
"""
from __future__ import annotations

import os
from core.auth import AuthProvider, UserContext


class InvalidTokenError(Exception):
    """token 不合法."""


# 演示 token. 环境变量 HIVESWARM_TOKENS 支持 "user:role,user:role" 覆盖.
_DEFAULT_TOKENS = {
    "mvp-token-admin": ("admin_user", "admin"),
    "mvp-token-dev": ("dev_user", "developer"),
    "mvp-token-view": ("viewer_user", "viewer"),
}


def _load_tokens() -> dict[str, tuple[str, str]]:
    env = os.getenv("HIVESWARM_TOKENS", "")
    if not env:
        return dict(_DEFAULT_TOKENS)
    out: dict[str, tuple[str, str]] = {}
    for pair in env.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        user, role = pair.split(":", 1)
        out[user.strip()] = (user.strip(), role.strip())
    return out


def _user_from_token(token: str, user_id: str, role: str) -> UserContext:
    return UserContext(user_id=user_id, role=role, tenant_id="default", anonymous=False)


class SimpleAuth(AuthProvider):
    """MVP 鉴权. 接受三个 demo token + 环境变量覆盖."""

    def __init__(self, default_user: str = "mvp_user") -> None:
        self._default = default_user
        self._tokens = _load_tokens()

    def check_token(self, token: str) -> UserContext:
        if not token:
            return UserContext(user_id="anonymous", role="viewer", tenant_id="default", anonymous=True)

        if token in self._tokens:
            user_id, role = self._tokens[token]
            return _user_from_token(token, user_id, role)

        raise InvalidTokenError("unknown token (use mvp-token-admin / -dev / -view)")

    def whoami(self) -> UserContext:
        return _user_from_token("internal", self._default, "admin")