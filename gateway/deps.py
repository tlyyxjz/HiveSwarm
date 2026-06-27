"""FastAPI dependency injection helpers.

按 FastAPI 标准做法, 路由用 Depends(get_xxx) 而不是直接 Request.app.state.xxx.

留活路:
  - 单测可用 app.dependency_overrides[get_pool] = lambda: mock_pool
  - 加 rate-limit / cache 中间件直接挂 deps 上即可
  - 加新组件 (e.g. Redis 缓存) 只需在这里加一个 getter, 路由加一个参数

路由当前用 Request.app.state, 是为了快上. 切换工作单做.
"""
from __future__ import annotations

from fastapi import Request

from stub.services import Services
from layers.work.pool import SkillPool
from layers.brain.planner import MockBrain
from layers.work.factory import AgentFactory
from layers.memory.store import MemoryStore
from stub.bus_local import LocalEventBus


def get_services(request: Request) -> Services:
    return request.app.state.services


def get_pool(request: Request) -> SkillPool:
    return request.app.state.pool


def get_brain(request: Request) -> MockBrain:
    return request.app.state.brain


def get_factory(request: Request) -> AgentFactory:
    return request.app.state.factory


def get_memory(request: Request) -> MemoryStore:
    return request.app.state.memory


def get_bus(request: Request) -> LocalEventBus:
    return request.app.state.bus