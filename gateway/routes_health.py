"""Health check endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Request
from gateway.models import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request):
    """System health check endpoint."""
    pool = request.app.state.pool
    return HealthResponse(
        status="ok",
        version="0.1.0",
        pool_size=len(pool.list_available()),
    )