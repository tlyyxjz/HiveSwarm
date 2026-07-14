"""Gateway Auth Middleware 单测 - 鉴权链路."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.responses import JSONResponse

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from gateway.middleware.auth_bootstrap import (
    EXEMPT_PATHS,
    LazyAuthMiddleware,
    bootstrap_auth,
)


def make_request(path: str, auth_header: str | None = None, app: MagicMock | None = None) -> MagicMock:
    req = MagicMock()
    req.url.path = path
    req.headers = {"Authorization": auth_header} if auth_header else {}
    if app is not None:
        req.app = app  # 显式链到我 app
    return req


def make_app(services=None) -> MagicMock:
    """构造 mock app with 真 state.services."""
    app = MagicMock()
    state = SimpleNamespace(services=services)
    type(app).state = property(lambda self: state)
    return app


def make_response(status_code: int = 200):
    if status_code == 200:
        return MagicMock(status_code=200)
    # 401/503 等错误: 用真 JSONResponse
    return JSONResponse(status_code=status_code, content={"detail": "mock"})


class TestExemptPaths:
    def test_health_exempt(self):
        assert "/health" in EXEMPT_PATHS

    def test_docs_exempt(self):
        assert "/docs" in EXEMPT_PATHS

    def test_openapi_exempt(self):
        assert "/openapi.json" in EXEMPT_PATHS

    def test_redoc_exempt(self):
        assert "/redoc" in EXEMPT_PATHS


class TestDispatch:
    def test_exempt_path_passes_through(self):
        mw = LazyAuthMiddleware(app=make_app())
        req = make_request("/health")
        call_next = AsyncMock(return_value=make_response())

        async def runner():
            return await mw.dispatch(req, call_next)

        asyncio.run(runner())
        call_next.assert_called_once_with(req)

    def test_missing_authorization_returns_401(self):
        mw = LazyAuthMiddleware(app=make_app(services=MagicMock()))
        req = make_request("/tasks")
        call_next = AsyncMock()

        async def runner():
            return await mw.dispatch(req, call_next)

        resp = asyncio.run(runner())
        assert resp.status_code == 401
        call_next.assert_not_called()

    def test_non_bearer_auth_returns_401(self):
        mw = LazyAuthMiddleware(app=make_app(services=MagicMock()))
        req = make_request("/tasks", auth_header="Basic dXNlcjpwYXNz")
        call_next = AsyncMock()

        async def runner():
            return await mw.dispatch(req, call_next)

        resp = asyncio.run(runner())
        assert resp.status_code == 401

    def test_services_not_initialized_returns_503(self):
        app = make_app(services=None)
        mw = LazyAuthMiddleware(app=app)
        req = make_request("/tasks", auth_header="Bearer valid-token", app=app)
        call_next = AsyncMock()

        async def runner():
            return await mw.dispatch(req, call_next)

        resp = asyncio.run(runner())
        assert resp.status_code == 503
        call_next.assert_not_called()

    def test_valid_token_sets_user_state(self):
        mock_user = MagicMock()
        mock_user.user_id = "alice"
        services = MagicMock()
        services.auth.check_token = MagicMock(return_value=mock_user)

        app = make_app(services=services)
        mw = LazyAuthMiddleware(app=app)
        req = make_request("/tasks", auth_header="Bearer valid-token-abc", app=app)
        call_next = AsyncMock(return_value=make_response())

        async def runner():
            await mw.dispatch(req, call_next)

        asyncio.run(runner())
        call_next.assert_called_once_with(req)
        assert req.state.user == mock_user

    def test_invalid_token_returns_401(self):
        services = MagicMock()
        services.auth.check_token = MagicMock(side_effect=ValueError("bad signature"))

        app = make_app(services=services)
        mw = LazyAuthMiddleware(app=app)
        req = make_request("/tasks", auth_header="Bearer invalid-token", app=app)
        call_next = AsyncMock()

        async def runner():
            return await mw.dispatch(req, call_next)

        resp = asyncio.run(runner())
        assert resp.status_code == 401
        call_next.assert_not_called()

    def test_bearer_with_whitespace_extracted(self):
        mock_user = MagicMock()
        services = MagicMock()
        services.auth.check_token = MagicMock(return_value=mock_user)

        app = make_app(services=services)
        mw = LazyAuthMiddleware(app=app)
        req = make_request("/tasks", auth_header="Bearer    token-with-spaces   ", app=app)
        call_next = AsyncMock(return_value=make_response())

        async def runner():
            await mw.dispatch(req, call_next)

        asyncio.run(runner())
        services.auth.check_token.assert_called_once_with("token-with-spaces")


class TestBootstrap:
    def test_bootstrap_registers_middleware(self):
        app = MagicMock()
        bootstrap_auth(app)
        app.add_middleware.assert_called_once()
        call_args = app.add_middleware.call_args
        assert call_args[0][0] is LazyAuthMiddleware