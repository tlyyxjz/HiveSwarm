"""Task endpoints - submit and retrieve tasks."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from layers.memory.store import MemoryTier
from layers.work.transaction import TaskTransaction
from layers.work.skill_registry import register_needed_skills
from gateway.models import TaskRequest, TaskResponse, TaskAcceptedResponse

if TYPE_CHECKING:
    from core.brain import SubTask

router = APIRouter()


def _build_subtask_input(subtask: "SubTask", request: TaskRequest) -> dict:
    """Build input data for a subtask based on its type."""
    if any(s.startswith("agentvet_") for s in subtask.required_skills):
        return {"target": request.target or "."}
    elif "outline" in subtask.required_skills:
        return {"facts": ["fact_a", "fact_b", "fact_c"]}
    elif "export" in subtask.required_skills:
        return {"layouts": ["title", "content"]}
    else:
        return {"topic": request.request}


def _run_plan_sync(plan, task_request, pool, factory):
    """Synchronous plan execution (runs in thread executor)."""
    with TaskTransaction(pool, factory, plan.task_id) as tx:
        results = []
        for sub in plan.subtasks:
            inp = _build_subtask_input(sub, task_request)
            r = tx.add(sub).run(inp)
            results.append({
                "sub_id": r.sub_id,
                "ok": r.ok,
                "error": r.error,
                "result": r.result,
            })
    return {
        "results": results,
        "all_ok": tx._result.all_ok,
        "success_count": tx._result.success_count,
        "fail_count": tx._result.fail_count,
    }


async def _execute_plan(plan, task_request, pool, factory, memory):
    """Execute a plan asynchronously."""
    loop = asyncio.get_running_loop()
    tx_result = await loop.run_in_executor(
        None, lambda: _run_plan_sync(plan, task_request, pool, factory)
    )

    final = {
        "task_id": plan.task_id,
        "request": task_request.request,
        "rationale": plan.rationale,
        "subtasks": [s.sub_id for s in plan.subtasks],
        "results": tx_result["results"],
        "all_ok": tx_result["all_ok"],
        "success_count": tx_result["success_count"],
        "fail_count": tx_result["fail_count"],
    }

    memory.put(MemoryTier.LONG, f"task:{plan.task_id}", final)
    return final


@router.post("/")
async def create_task(
    body: TaskRequest,
    bg: BackgroundTasks,
    request: Request,
):
    """Submit a task for execution.

    Returns TaskResponse (sync) or TaskAcceptedResponse (async).
    """
    state = request.app.state
    pool = state.pool
    factory = state.factory
    memory = state.memory

    # 1. Brain plans
    plan = await state.brain.plan(body.request)

    # 2. Register needed skills
    register_needed_skills(pool, plan)

    # 3. Async mode: fire-and-forget
    if body.async_mode:
        bg.add_task(_execute_plan, plan, body, pool, factory, memory)
        return TaskAcceptedResponse(task_id=plan.task_id)

    # 4. Sync: execute immediately
    final = await _execute_plan(plan, body, pool, factory, memory)
    return TaskResponse(**final)


@router.get("/{task_id}")
async def get_task(task_id: str, request: Request):
    """Retrieve a completed task result."""
    memory = request.app.state.memory
    result = memory.get(MemoryTier.LONG, f"task:{task_id}")
    if result is None:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")
    return TaskResponse(**result)