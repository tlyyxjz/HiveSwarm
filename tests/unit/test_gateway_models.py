"""Gateway Pydantic model tests."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from gateway.models import (
    TaskRequest, TaskResponse, TaskAcceptedResponse,
    SubTaskResultResponse, SkillsResponse, SkillInfo, HealthResponse,
    task_response_from_result,
)


class TestTaskRequest:
    def test_valid_request(self):
        req = TaskRequest(request="make a PPT")
        assert req.request == "make a PPT"
        assert req.target is None
        assert req.async_mode is False

    def test_missing_request_raises(self):
        with pytest.raises(ValidationError):
            TaskRequest()

    def test_with_target(self):
        req = TaskRequest(request="scan", target="/tmp/project")
        assert req.target == "/tmp/project"

    def test_async_mode(self):
        req = TaskRequest(request="x", async_mode=True)
        assert req.async_mode is True


class TestTaskResponse:
    def test_valid_response(self):
        resp = TaskResponse(
            task_id="t1",
            request="make a PPT",
            rationale="test",
            subtasks=["s1", "s2"],
            results=[
                SubTaskResultResponse(sub_id="s1", ok=True, result={"x": 1}),
                SubTaskResultResponse(sub_id="s2", ok=False, error="boom"),
            ],
            all_ok=False,
            success_count=1,
            fail_count=1,
        )
        assert resp.task_id == "t1"
        assert not resp.all_ok
        assert len(resp.results) == 2


class TestSkillsResponse:
    def test_empty_skills(self):
        resp = SkillsResponse(skills=[])
        assert resp.skills == []

    def test_with_skills(self):
        resp = SkillsResponse(skills=[
            SkillInfo(name="a", api_version="1.0", refcount=0, health={}),
        ])
        assert len(resp.skills) == 1


class TestHealthResponse:
    def test_defaults(self):
        resp = HealthResponse()
        assert resp.status == "ok"
        assert resp.version == "0.1.0"


class TestTaskResponseFromResult:
    def test_builds_response(self):
        resp = task_response_from_result(
            task_id="t1",
            request="x",
            rationale="test",
            subtask_ids=["s1"],
            results=[{"sub_id": "s1", "ok": True, "result": {"x": 1}}],
            all_ok=True,
            success_count=1,
            fail_count=0,
        )
        assert isinstance(resp, TaskResponse)
        assert resp.all_ok is True