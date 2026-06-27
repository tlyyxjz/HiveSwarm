"""HiveSwarm Python SDK client."""
from __future__ import annotations

import json
import asyncio
from typing import AsyncGenerator, Optional
import httpx

from gateway.models import (
    TaskRequest, TaskResponse, TaskAcceptedResponse,
    SkillsResponse, HealthResponse
)


class HiveSwarmClient:
    """Async HTTP client for HiveSwarm gateway."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = 120.0,
        http_client: Optional[httpx.AsyncClient] = None
    ):
        """Initialize the client.

        Args:
            base_url: Base URL of the HiveSwarm gateway (e.g., "http://localhost:8000")
            timeout: Default timeout for requests in seconds
            http_client: Optional custom httpx client (for testing/mocking)
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = http_client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout
        )

    # --- Task Management ---

    async def submit_task(
        self,
        request: str,
        *,
        target: Optional[str] = None,
        async_mode: bool = False
    ) -> TaskResponse | TaskAcceptedResponse:
        """Submit a task for execution.

        Args:
            request: Natural language task description
            target: Optional target path for scan-type tasks
            async_mode: If True, returns immediately with task_id

        Returns:
            TaskResponse for sync execution
            TaskAcceptedResponse for async execution
        """
        body = TaskRequest(request=request, target=target, async_mode=async_mode)
        response = await self._client.post("/tasks", json=body.model_dump())
        response.raise_for_status()
        data = response.json()

        if data.get("status") == "accepted":
            return TaskAcceptedResponse(**data)
        return TaskResponse(**data)

    async def get_task(self, task_id: str) -> TaskResponse:
        """Get the result of a completed task.

        Args:
            task_id: The task identifier

        Returns:
            TaskResponse with complete results

        Raises:
            httpx.HTTPStatusError: If task not found or other error
        """
        response = await self._client.get(f"/tasks/{task_id}")
        response.raise_for_status()
        return TaskResponse(**response.json())

    # --- Skills Management ---

    async def list_skills(self) -> SkillsResponse:
        """List all available skills with health status.

        Returns:
            SkillsResponse containing list of available skills
        """
        response = await self._client.get("/skills")
        response.raise_for_status()
        return SkillsResponse(**response.json())

    # --- Event Streaming ---

    async def stream_events(self) -> AsyncGenerator[dict, None]:
        """Stream events as Server-Sent Events.

        Yields:
            Event dictionaries from the SSE stream
        """
        async with self._client.stream("GET", "/events") as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    event_data = json.loads(line[6:])
                    yield event_data
                # Keepalive lines (:) and empty lines are ignored

    # --- Health Check ---

    async def health(self) -> HealthResponse:
        """Check system health.

        Returns:
            HealthResponse with system status
        """
        response = await self._client.get("/health")
        response.raise_for_status()
        return HealthResponse(**response.json())

    # --- Utilities ---

    async def close(self) -> None:
        """Close the HTTP client connection."""
        await self._client.aclose()

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()


# Synchronous wrapper for convenience
class SyncHiveSwarmClient:
    """Synchronous wrapper for HiveSwarmClient."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = 120.0
    ):
        """Initialize synchronous client."""
        self.base_url = base_url
        self.timeout = timeout

    def submit_task(
        self,
        request: str,
        *,
        target: Optional[str] = None,
        async_mode: bool = False
    ) -> TaskResponse | TaskAcceptedResponse:
        """Submit task synchronously."""
        async def _submit():
            async with HiveSwarmClient(
                self.base_url,
                self.timeout
            ) as client:
                return await client.submit_task(request, target=target, async_mode=async_mode)

        return asyncio.run(_submit())

    def get_task(self, task_id: str) -> TaskResponse:
        """Get task result synchronously."""
        async def _get():
            async with HiveSwarmClient(
                self.base_url,
                self.timeout
            ) as client:
                return await client.get_task(task_id)

        return asyncio.run(_get())

    def list_skills(self) -> SkillsResponse:
        """List skills synchronously."""
        async def _list():
            async with HiveSwarmClient(
                self.base_url,
                self.timeout
            ) as client:
                return await client.list_skills()

        return asyncio.run(_list())

    def stream_events(self):
        """Stream events synchronously (blocking)."""
        async def _stream():
            async with HiveSwarmClient(
                self.base_url,
                self.timeout
            ) as client:
                async for event in client.stream_events():
                    yield event

        for event in asyncio.run(_stream()):
            yield event

    def health(self) -> HealthResponse:
        """Check health synchronously."""
        async def _health():
            async with HiveSwarmClient(
                self.base_url,
                self.timeout
            ) as client:
                return await client.health()

        return asyncio.run(_health())