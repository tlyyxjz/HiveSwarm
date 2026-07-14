"""HiveSwarm SDK client e2e - mock httpx, asyncio.run 模式."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "sdk"))

from hiveswarm_client.client import HiveSwarmClient, SyncHiveSwarmClient


def make_mock_http(handler):
    """构造 mock httpx client. handler(method, url, body) -> (status, body)."""
    mock = MagicMock()
    mock.aclose = AsyncMock()

    async def post(url, json=None, **kw):
        status, body = handler("POST", url, json)
        return _make_resp(status, body)

    async def get(url, **kw):
        status, body = handler("GET", url, None)
        return _make_resp(status, body)

    mock.post = AsyncMock(side_effect=post)
    mock.get = AsyncMock(side_effect=get)
    return mock


def _make_resp(status, body):
    resp = MagicMock()
    resp.status_code = status
    resp.json = lambda b=body: b
    resp.raise_for_status = lambda: (
        (_ for _ in ()).throw(
            httpx.HTTPStatusError("err", request=MagicMock(), response=resp)
        )
        if status >= 400 else None
    )
    return resp


def full_task_response(task_id="t-1", request="test"):
    return {
        "task_id": task_id,
        "request": request,
        "rationale": "mock rationale",
        "subtasks": ["s1", "s2", "s3", "s4"],
        "results": [
            {"sub_id": "s1", "ok": True, "error": None, "result": {"echo": 1}},
            {"sub_id": "s2", "ok": True, "error": None, "result": {"echo": 2}},
        ],
        "all_ok": True,
        "success_count": 2,
        "fail_count": 0,
    }


def full_skill_info(name, **overrides):
    base = {
        "name": name,
        "api_version": "1.0",
        "description": f"fake {name}",
        "tags": [],
        "refcount": 0,
        "health": {"success_count": 0, "failure_count": 0, "error_rate": 0.0},
    }
    base.update(overrides)
    return base


class TestConstruction:
    def test_default_base_url(self):
        c = HiveSwarmClient()
        assert c.base_url == "http://localhost:8000"

    def test_strip_trailing_slash(self):
        c = HiveSwarmClient(base_url="http://x:8000/")
        assert c.base_url == "http://x:8000"

    def test_custom_timeout(self):
        c = HiveSwarmClient(timeout=10.0)
        assert c.timeout == 10.0

    def test_async_context_manager_closes(self):
        mock_http = make_mock_http(lambda m, u, b: (200, {"status": "ok"}))

        async def runner():
            c = HiveSwarmClient(http_client=mock_http)
            async with c:
                pass

        asyncio.run(runner())
        mock_http.aclose.assert_called_once()


class TestSubmitTask:
    def test_submit_sync_mode(self):
        captured = {}

        def handler(method, url, body):
            captured["url"] = url
            captured["body"] = body
            return 200, full_task_response("t-123", "做一个 PPT")

        mock_http = make_mock_http(handler)
        c = HiveSwarmClient(http_client=mock_http)
        result = asyncio.run(c.submit_task("做一个 PPT"))
        assert captured["url"] == "/tasks"
        assert captured["body"]["request"] == "做一个 PPT"
        assert captured["body"]["async_mode"] is False
        assert result.task_id == "t-123"
        assert result.all_ok is True
        assert result.success_count == 2

    def test_submit_async_mode_returns_accepted(self):
        mock_http = make_mock_http(
            lambda m, u, b: (200, {"task_id": "t-456", "status": "accepted"})
        )
        c = HiveSwarmClient(http_client=mock_http)
        result = asyncio.run(c.submit_task("做 PPT", async_mode=True))
        assert result.task_id == "t-456"
        assert result.status == "accepted"

    def test_submit_with_target(self):
        captured = {}
        mock_http = make_mock_http(
            lambda m, u, b: (captured.update({"body": b}) or 200, full_task_response("t"))
        )
        c = HiveSwarmClient(http_client=mock_http)
        asyncio.run(c.submit_task("scan", target="/path/to/code"))
        assert captured["body"]["target"] == "/path/to/code"

    def test_submit_404_raises(self):
        mock_http = make_mock_http(lambda m, u, b: (404, {"detail": "not found"}))
        c = HiveSwarmClient(http_client=mock_http)
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(c.submit_task("x"))


class TestGetTask:
    def test_get_task_success(self):
        mock_http = make_mock_http(
            lambda m, u, b: (200, full_task_response("t-1"))
        )
        c = HiveSwarmClient(http_client=mock_http)
        result = asyncio.run(c.get_task("t-1"))
        assert result.task_id == "t-1"
        assert len(result.subtasks) == 4

    def test_get_task_url_format(self):
        captured = {}
        mock_http = make_mock_http(
            lambda m, u, b: (captured.update({"url": u}) or 200, full_task_response("t-1"))
        )
        c = HiveSwarmClient(http_client=mock_http)
        asyncio.run(c.get_task("my-task-id"))
        assert captured["url"] == "/tasks/my-task-id"


class TestListSkills:
    def test_list_skills(self):
        mock_http = make_mock_http(
            lambda m, u, b: (200, {
                "skills": [
                    full_skill_info("agentvet_l1"),
                    full_skill_info("ppt_export", refcount=2, health={
                        "success_count": 3, "failure_count": 1, "error_rate": 0.25
                    }),
                ]
            })
        )
        c = HiveSwarmClient(http_client=mock_http)
        result = asyncio.run(c.list_skills())
        assert len(result.skills) == 2
        assert result.skills[0].name == "agentvet_l1"
        assert result.skills[1].refcount == 2
        assert result.skills[1].health["error_rate"] == 0.25


class TestHealth:
    def test_health_ok(self):
        mock_http = make_mock_http(lambda m, u, b: (200, {"status": "ok", "version": "0.2.0", "pool_size": 4}))
        c = HiveSwarmClient(http_client=mock_http)
        result = asyncio.run(c.health())
        assert result.status == "ok"
        assert result.pool_size == 4

    def test_health_url(self):
        captured = {}
        mock_http = make_mock_http(
            lambda m, u, b: (captured.update({"url": u}) or 200, {"status": "ok", "version": "0.2.0"})
        )
        c = HiveSwarmClient(http_client=mock_http)
        asyncio.run(c.health())
        assert captured["url"] == "/health"


class TestStreamEvents:
    def test_stream_yields_parsed_events(self):
        class FakeResp:
            status_code = 200

            def raise_for_status(self):
                pass

            async def aiter_lines(self):
                yield ":keepalive"
                yield ""
                yield 'data: {"type": "task.started", "task_id": "t-1"}'
                yield ""
                yield 'data: {"type": "task.completed", "task_id": "t-1"}'

        stream_cm = MagicMock()
        stream_cm.__aenter__ = AsyncMock(return_value=FakeResp())
        stream_cm.__aexit__ = AsyncMock(return_value=None)

        mock_http = MagicMock()
        mock_http.stream = MagicMock(return_value=stream_cm)
        mock_http.aclose = AsyncMock()

        c = HiveSwarmClient(http_client=mock_http)

        async def collect():
            return [ev async for ev in c.stream_events()]

        events = asyncio.run(collect())
        assert len(events) == 2
        assert events[0]["type"] == "task.started"
        assert events[1]["task_id"] == "t-1"


class TestSyncClient:
    def test_sync_client_api_shape(self):
        sc = SyncHiveSwarmClient(base_url="http://x:8000", timeout=5.0)
        assert sc.base_url == "http://x:8000"
        assert sc.timeout == 5.0
        for method in ("submit_task", "get_task", "list_skills", "health", "stream_events"):
            assert hasattr(sc, method)