"""FastAPI app factory with lifespan management."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
import logging

from stub.services import build_default_services
from stub.bus_local import LocalEventBus
from layers.work.pool import SkillPool
from layers.brain.planner import LLMBrain, MockBrain
from layers.work.factory import AgentFactory
from layers.memory.store import MemoryStore
from layers.memory.store import MemoryTier

# Silence some noisy loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App startup/shutdown lifecycle manager.

    On startup:
    - Load config from app.state.config_path
    - Build Services aggregate root
    - Create runtime objects (SkillPool, Brain, Factory, Memory)
    - Attach to app.state for dependency injection

    On shutdown:
    - Call services.shutdown() to clean up resources
    """
    # Load config and build services
    config_path = getattr(app.state, "config_path", None)
    if config_path:
        services = build_default_services(config=config_path)
    else:
        services = build_default_services()

    # Extract and instantiate runtime components (mirrors src/main.py structure)
    bus = services.bus              # LocalEventBus from Services
    pool = SkillPool(bus=bus)       # SkillPool needs bus for events
    from stub.config_loader import load_config
    cfg = load_config(config_path) if config_path else load_config()
    try:
        brain = LLMBrain(system_prompt=cfg.brain.planner_system_prompt, model=cfg.brain.llm_model, cfg=cfg)
        # LLMBrain 在 plan() 时用 cfg.providers 选模型，无可用 provider 自动降级 MockBrain
    except Exception:
        brain = MockBrain()
    factory = AgentFactory(pool)     # Factory needs pool for checkout
    memory = MemoryStore(services.memory)  # Wrap SQLiteStore from Services

    # Store all components on app.state for dependency injection
    app.state.services = services
    app.state.pool = pool
    app.state.brain = brain
    app.state.factory = factory
    app.state.memory = memory
    app.state.bus = bus

    # Startup complete
    yield

    # Cleanup
    try:
        services.shutdown()
    except Exception as exc:
        logging.warning("Error during shutdown: %s", exc)


def create_app(config_path: str | None = None) -> FastAPI:
    """Create FastAPI application with components.

    Args:
        config_path: Optional path to config file (default: config/mvp.toml)
    """
    app = FastAPI(
        title="HiveSwarm",
        description="Multi-agent coordination framework with dynamic skill equipping",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Store config path for lifespan use
    app.state.config_path = config_path

    # Add auth middleware (uses services.auth created in lifespan)
    # NOTE: middleware runs BEFORE lifespan, so we need a placeholder auth
    # and replace it after lifespan. Or read services inside middleware.
    # For MVP: services is built lazily, middleware accesses services via app.state.
    from gateway.middleware.auth_bootstrap import bootstrap_auth
    bootstrap_auth(app)

    # Include routers (import after app creation to avoid circular imports)
    from gateway.routes_tasks import router as tasks_router
    from gateway.routes_skills import router as skills_router
    from gateway.routes_events import router as events_router
    from gateway.routes_health import router as health_router

    app.include_router(tasks_router, prefix="/tasks", tags=["tasks"])
    app.include_router(skills_router, prefix="/skills", tags=["skills"])
    app.include_router(events_router, tags=["events"])
    app.include_router(health_router, tags=["health"])

    return app


# Development entry point
if __name__ == "__main__":  # pragma: no cover
    import uvicorn
    app = create_app()
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )