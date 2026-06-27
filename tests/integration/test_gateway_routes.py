"""Gateway route integration tests using TestClient."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from gateway.app import create_app


AUTH_HEADER = {"Authorization": "Bearer mvp-token-admin"}


@pytest.fixture
def client():
    """Create test client with app."""
    app = create_app()
    with TestClient(app) as c:
        yield c


class TestHealthRoute:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "pool_size" in data


class TestSkillsRoute:
    def test_skills_returns_empty(self, client):
        resp = client.get("/skills/", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert "skills" in data


class TestTasksRoute:
    def test_submit_ppt_task(self, client):
        resp = client.post("/tasks/", json={
            "request": "帮我做一个 PPT",
        }, headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["all_ok"] is True
        assert "task_id" in data
        assert "results" in data

    def test_submit_async_task(self, client):
        resp = client.post("/tasks/", json={
            "request": "帮我做一个 PPT",
            "async_mode": True,
        }, headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"
        assert "task_id" in data

    def test_get_task_404(self, client):
        resp = client.get("/tasks/nonexistent", headers=AUTH_HEADER)
        assert resp.status_code == 404


class TestEventsRoute:
    def test_events_route_registered(self, client):
        """SSE endpoint is registered (streaming not tested with sync TestClient)."""
        from gateway.app import create_app
        app = create_app()
        routes = [r.path for r in app.routes]
        assert "/events" in routes


class TestAuthMiddleware:
    def test_no_token_returns_401(self, client):
        resp = client.post("/tasks/", json={"request": "hi"})
        assert resp.status_code == 401
        assert "Bearer" in resp.json()["detail"]

    def test_bad_token_returns_401(self, client):
        resp = client.post(
            "/tasks/", json={"request": "hi"},
            headers={"Authorization": "Bearer bogus-token"}
        )
        assert resp.status_code == 401
        assert "invalid token" in resp.json()["detail"]

    def test_health_exempt_from_auth(self, client):
        """Health endpoint should work without any token."""
        resp = client.get("/health")
        assert resp.status_code == 200


class TestEndToEndChain:
    """端到端: gateway → pool → skill → memory."""

    def test_ppt_task_registers_skills_in_pool(self, client):
        """PPT 任务跑完后, skill 池应非空（MockBrain 或 LLMBrain 都会注册技能）."""
        client.post("/tasks/", json={"request": "帮我做一个 PPT"}, headers=AUTH_HEADER)
        resp = client.get("/skills/", headers=AUTH_HEADER)
        data = resp.json()
        names = {s["name"] for s in data["skills"]}
        assert len(names) > 0, f"Pool should have skills registered, got: {names}"

    def test_task_result_persisted_in_memory(self, client):
        """同步任务结果存在 memory 里, GET /tasks/{id} 能取回."""
        r1 = client.post("/tasks/", json={"request": "帮我做一个 PPT"}, headers=AUTH_HEADER)
        task_id = r1.json()["task_id"]
        r2 = client.get(f"/tasks/{task_id}", headers=AUTH_HEADER)
        assert r2.status_code == 200
        assert r2.json()["task_id"] == task_id