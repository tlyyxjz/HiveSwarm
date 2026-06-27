"""OAuth2 / JWT Auth provider stub.

生产替换: 把 stub.auth_simple.SimpleAuth 换成 OAuthAuth,
        仅改 config.provider + config.options. 核心代码 0 改.

依赖: PyJWT + requests_oauthlib (TYPE_CHECKING 软依赖,未装也能 import).
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import TYPE_CHECKING, Any

from core.auth import AuthProvider, UserContext

if TYPE_CHECKING:  # 仅给类型检查,运行时不强依赖
    import jwt  # PyJWT

_log = logging.getLogger(__name__)


class InvalidTokenError(Exception):
    """Token 验失败. 业务层捕获处理."""


class OAuthAuth(AuthProvider):
    """OAuth2 / JWT 鉴权. 验 JWT via JWKS endpoint.

    Args:
        issuer: token 颁发者 (iss 声明)
        jwks_url: 公钥集 URL (公司 IdP 提供)
        audience: token 受众 (aud 声明)
        timeout_s: JWKS 拉取超时
    """

    def __init__(
        self,
        issuer: str,
        jwks_url: str,
        audience: str,
        timeout_s: float = 5.0,
    ) -> None:
        self._issuer = issuer
        self._jwks_url = jwks_url
        self._audience = audience
        self._timeout = timeout_s
        self._jwks_cache: dict[str, Any] | None = None

    def _get_jwks(self) -> dict[str, Any]:
        """拉 + 缓存 JWKS. 失败抛 InvalidTokenError."""
        if self._jwks_cache is None:
            try:
                with urllib.request.urlopen(self._jwks_url, timeout=self._timeout) as resp:
                    self._jwks_cache = json.loads(resp.read())
            except Exception as exc:
                _log.warning("JWKS fetch failed: %s", exc, exc_info=True)
                raise InvalidTokenError(f"JWKS fetch failed: {exc}") from exc
        return self._jwks_cache

    def _parse_token(self, token: str) -> dict[str, Any]:
        """验 token 签名 + 过期 + audience/issuer. 返回 claims."""
        import jwt  # 运行时 import,允许未装

        try:
            jwks = self._get_jwks()
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
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
            return claims
        except InvalidTokenError:
            raise
        except Exception as exc:
            _log.warning("token parse failed: %s", exc, exc_info=True)
            raise InvalidTokenError(str(exc)) from exc

    def check_token(self, token: str) -> UserContext:
        """验 Bearer token → UserContext."""
        if not token:
            return UserContext(user_id="anonymous", role="viewer", tenant_id="default", anonymous=True)
        claims = self._parse_token(token)
        return UserContext(
            user_id=str(claims.get("sub", "unknown")),
            role=str(claims.get("role", "viewer")),
            tenant_id=str(claims.get("tenant", "default")),
            anonymous=False,
        )

    def whoami(self) -> UserContext:
        """SDK 内部用: 从环境变量 HIVESWARM_SERVICE_TOKEN 读 service token."""
        svc = os.getenv("HIVESWARM_SERVICE_TOKEN", "")
        if not svc:
            return UserContext(user_id="service", role="admin", anonymous=True)
        return self.check_token(svc)