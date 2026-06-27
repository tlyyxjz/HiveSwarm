"""Auth middleware — lazy lookup 模式.

lifespan 创建 services.auth, middleware 在 dispatch 时才查.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


EXEMPT_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/docs/oauth2-redirect"}


class LazyAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        services = getattr(request.app.state, "services", None)
        if services is None:
            return JSONResponse(status_code=503, content={"detail": "server initializing"})

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "missing Bearer token"})

        token = auth_header[len("Bearer "):].strip()
        try:
            user = services.auth.check_token(token)
        except Exception as exc:
            return JSONResponse(status_code=401, content={"detail": f"invalid token: {exc}"})

        request.state.user = user
        return await call_next(request)


def bootstrap_auth(app: FastAPI) -> None:
    app.add_middleware(LazyAuthMiddleware)