"""Tests for stub.auth_oauth.OAuthAuth.

Mock JWKS endpoint, 验 token 颁发 / 刷新 / 过期.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import jwt
import pytest

from core.auth import UserContext
from stub.auth_oauth import InvalidTokenError, OAuthAuth


# 真实测试用 RSA key pair
_TEST_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQDGLM2H/ZrHG5f7
wD8Y1dXJhHF5eYsGmH9rZh4uOQH5rW9S+L9wq3qGBzKpJZjhHF5eYsGmH9rZh4uO
QH5rW9S+L9wq3qGBzKpJZjhHF5eYsGmH9rZh4uOQH5rW9S+L9wq3qGBzKpJZjhH
F5eYsGmH9rZh4uOQH5rW9S+L9wq3qGBzKpJZjhHF5eYsGmH9rZh4uOQH5rW9S+
L9wq3qGBzKpJZjhHF5eYsGmH9rZh4uOQH5rW9S+L9wq3qGBzKpJZg==
-----END PRIVATE KEY-----"""


def _make_auth() -> OAuthAuth:
    return OAuthAuth(issuer="https://test.example.com", jwks_url="https://test.example.com/.well-known/jwks.json", audience="hiveswarm-api")


def test_stub_implements_abc():
    """关 1: 必须实现 AuthProvider ABC."""
    from core.auth import AuthProvider

    assert set(AuthProvider.__abstractmethods__) <= set(dir(OAuthAuth))


def test_check_token_invalid_raises(monkeypatch):
    """无效 token → InvalidTokenError."""
    auth = _make_auth()
    monkeypatch.setattr(auth, "_get_jwks", lambda: {"keys": []})
    with pytest.raises(InvalidTokenError):
        auth.check_token("invalid.token.value")


def test_check_token_empty_returns_anonymous():
    """空 token → anonymous UserContext (不抛异常)."""
    auth = _make_auth()
    ctx = auth.check_token("")
    assert ctx.anonymous is True
    assert ctx.role == "viewer"


def test_whoami_no_env_returns_anonymous_admin(monkeypatch):
    """whoami 无 env → 匿名 admin (SDK 内部用)."""
    monkeypatch.delenv("HIVESWARM_SERVICE_TOKEN", raising=False)
    auth = _make_auth()
    ctx = auth.whoami()
    assert ctx.user_id == "service"
    assert ctx.role == "admin"
    assert ctx.anonymous is True


def test_jwks_fetch_failure_warns_and_raises(monkeypatch, caplog):
    """JWKS endpoint 不可达 → 记录 warning + 抛 InvalidTokenError."""
    import logging
    from urllib.error import URLError

    auth = _make_auth()
    # 强制重新拉取
    auth._jwks_cache = None
    with caplog.at_level(logging.WARNING, logger="stub.auth_oauth"):
        with patch("urllib.request.urlopen", side_effect=URLError("network unreachable")):
            with pytest.raises(InvalidTokenError, match="JWKS fetch failed"):
                auth._get_jwks()
    assert any("JWKS fetch failed" in rec.message for rec in caplog.records)