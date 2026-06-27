"""Skills endpoint - list available skills."""
from __future__ import annotations

from fastapi import APIRouter, Request
from gateway.models import SkillsResponse, SkillInfo

router = APIRouter()


@router.get("/", response_model=SkillsResponse)
async def list_skills(request: Request):
    """List all available skills with health status."""
    pool = request.app.state.pool
    health = pool.health_report()
    skills: list[SkillInfo] = []

    for name in pool.list_available():
        manifest = pool.get_manifest(name)
        if manifest is None:
            continue
        h = health.get(name, {})
        skills.append(SkillInfo(
            name=manifest["name"],
            api_version=manifest["api_version"],
            description=manifest["description"],
            tags=tuple(manifest["tags"]),
            refcount=h.get("refcount", 0),
            health=h.get("health", {}),
        ))

    return SkillsResponse(skills=skills)