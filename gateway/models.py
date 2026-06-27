"""Pydantic schemas for HiveSwarm gateway API."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


# Request models
class TaskRequest(BaseModel):
    """Submit a task request."""

    request: str = Field(..., min_length=1, max_length=2000)
    target: str | None = Field(None, max_length=500)
    async_mode: bool = False

    @field_validator("request")
    @classmethod
    def _request_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("request must not be blank")
        return stripped

    @field_validator("target")
    @classmethod
    def _target_safe_path(cls, v: str | None) -> str | None:
        """防路径遍历和 null byte."""
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if "\x00" in v:
            raise ValueError("target contains null byte")
        for sep in ("/", "\\"):
            if ".." in v.split(sep):
                raise ValueError("target must not contain '..'")
        return v


# Response models
class SubTaskResultResponse(BaseModel):
    """Result of a single subtask execution."""
    sub_id: str
    ok: bool
    error: str | None = None
    result: dict | None = None


class TaskResponse(BaseModel):
    """Complete task result response."""
    task_id: str
    request: str
    rationale: str
    subtasks: list[str]
    results: list[SubTaskResultResponse]
    all_ok: bool
    success_count: int
    fail_count: int


class TaskAcceptedResponse(BaseModel):
    """Response when async_mode is True."""
    task_id: str
    status: str = "accepted"        # for async_mode


class SkillInfo(BaseModel):
    """Combined skill info from manifest and pool health."""
    name: str
    api_version: str
    description: str = ""
    tags: tuple[str, ...] = ()
    refcount: int = 0
    health: dict = {}


class SkillsResponse(BaseModel):
    """List of available skills with health."""
    skills: list[SkillInfo]


class HealthResponse(BaseModel):
    """System health check response."""
    status: str = "ok"
    version: str = "0.1.0"
    pool_size: int = 0


def task_response_from_result(
    task_id: str,
    request: str,
    rationale: str,
    subtask_ids: list[str],
    results: list[dict],
    all_ok: bool,
    success_count: int,
    fail_count: int,
) -> TaskResponse:
    """Build TaskResponse from execution results.

    Args:
        task_id: Task identifier
        request: Original request string
        rationale: Brain's decomposition rationale
        subtask_ids: List of subtask IDs
        results: List of result dicts (sub_id, ok, error, result)
        all_ok: Whether everything succeeded
        success_count: Number of successful subtasks
        fail_count: Number of failed subtasks
    """
    return TaskResponse(
        task_id=task_id,
        request=request,
        rationale=rationale,
        subtasks=subtask_ids,
        results=[
            SubTaskResultResponse(
                sub_id=r["sub_id"],
                ok=r["ok"],
                error=r.get("error"),
                result=r.get("result"),
            )
            for r in results
        ],
        all_ok=all_ok,
        success_count=success_count,
        fail_count=fail_count,
    )