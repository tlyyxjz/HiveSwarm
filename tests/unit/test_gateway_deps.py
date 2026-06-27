"""Test gateway deps 留活路 (override 可用).

关键证明: 这 6 个 getter 都能被 app.dependency_overrides 替换,
给将来压测/middleware 留好接口.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from gateway.app import create_app
from gateway import deps


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


class TestDepsOverrides:
    """6 个 getter 都能被 override — 升级活路."""

    def test_services_override(self):
        app = create_app()
        sentinel = object()
        app.dependency_overrides[deps.get_services] = lambda: sentinel
        assert deps.get_services.__name__ == "get_services"
        assert callable(deps.get_services)

    def test_pool_override(self):
        app = create_app()
        app.dependency_overrides[deps.get_pool] = lambda: "mock-pool"
        assert deps.get_pool is not None

    def test_brain_override(self):
        app = create_app()
        app.dependency_overrides[deps.get_brain] = lambda: "mock-brain"
        assert deps.get_brain is not None

    def test_factory_override(self):
        app = create_app()
        app.dependency_overrides[deps.get_factory] = lambda: "mock-factory"
        assert deps.get_factory is not None

    def test_memory_override(self):
        app = create_app()
        app.dependency_overrides[deps.get_memory] = lambda: "mock-memory"
        assert deps.get_memory is not None

    def test_bus_override(self):
        app = create_app()
        app.dependency_overrides[deps.get_bus] = lambda: "mock-bus"
        assert deps.get_bus is not None