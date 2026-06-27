"""SkillPool 单元测试."""
from __future__ import annotations

import asyncio
import threading

import pytest

from core.events import EventType
from core.skill import Skill, SkillHealth, SkillManifest
from core.skill_bundle import SkillBundle, Borrowed
from layers.work.pool import SkillNotFoundError, SkillPool, SkillRetiredError
from stub.bus_local import LocalEventBus


class FakeSkill(Skill):
    def __init__(self, name: str, fail_health: bool = False) -> None:
        super().__init__(SkillManifest(name=name, api_version="1.0"))
        self.run_count = 0
        self._fail_health = fail_health

    def run(self, input_data: dict) -> dict:
        self.run_count += 1
        return {"ok": True, "name": self.manifest.name}

    async def health_check(self) -> SkillHealth:
        if self._fail_health:
            raise RuntimeError("intentional fail")
        return SkillHealth(
            name=self.manifest.name,
            success_count=1,
            failure_count=0,
        )


# ── 注册 / 列表 ─────────────────────────────────────────────────────────

class TestRegister:
    def test_register_and_list(self):
        pool = SkillPool()
        pool.register(FakeSkill("a"))
        pool.register(FakeSkill("b"))
        assert pool.list_available() == ("a", "b")
        assert pool.is_available("a")
        assert not pool.is_available("nope")

    def test_register_keeps_refcount_zero(self):
        pool = SkillPool()
        pool.register(FakeSkill("a"))
        assert pool.health_report()["a"]["refcount"] == 0


# ── 借 ─────────────────────────────────────────────────────────────────

class TestCheckout:
    def test_checkout_single(self):
        pool = SkillPool()
        pool.register(FakeSkill("a"))
        bundle = pool.checkout(["a"])
        assert isinstance(bundle, SkillBundle)
        assert bundle.names == ("a",)
        assert pool.health_report()["a"]["refcount"] == 1

    def test_checkout_multiple_atomic(self):
        """多个技能一起借, 全成功才 +1; 任一失败全回滚."""
        pool = SkillPool()
        pool.register(FakeSkill("a"))
        # b 没注册
        with pytest.raises(SkillNotFoundError, match="b"):
            pool.checkout(["a", "b"])
        # a 的 refcount 必须还是 0(回滚)
        assert pool.health_report()["a"]["refcount"] == 0

    def test_checkout_emits_event(self):
        bus = LocalEventBus()  # ABC, 用实现
        pool = SkillPool(bus=bus)
        pool.register(FakeSkill("a"))
        received: list[EventType] = []
        bus.subscribe(EventType.SKILL_CHECKED_OUT, lambda e: received.append(e.type))
        pool.checkout(["a"])
        assert received == [EventType.SKILL_CHECKED_OUT]

    def test_checkout_concurrent_limit(self):
        pool = SkillPool(max_concurrent_per_skill=2)
        pool.register(FakeSkill("a"))
        pool.checkout(["a"])
        pool.checkout(["a"])
        with pytest.raises(SkillRetiredError, match="limit"):
            pool.checkout(["a"])


# ── 还 ─────────────────────────────────────────────────────────────────

class TestReturn:
    def test_return_decrements_refcount(self):
        pool = SkillPool()
        pool.register(FakeSkill("a"))
        b = pool.checkout(["a"])
        assert pool.health_report()["a"]["refcount"] == 1
        pool.return_back(b)
        assert pool.health_report()["a"]["refcount"] == 0
        assert b.is_returned

    def test_return_already_returned_raises(self):
        pool = SkillPool()
        pool.register(FakeSkill("a"))
        b = pool.checkout(["a"])
        pool.return_back(b)
        with pytest.raises(RuntimeError, match="already returned"):
            pool.return_back(b)

    def test_return_emits_event(self):
        bus = LocalEventBus()
        pool = SkillPool(bus=bus)
        pool.register(FakeSkill("a"))
        got: list[EventType] = []
        bus.subscribe(EventType.SKILL_RETURNED, lambda e: got.append(e.type))
        b = pool.checkout(["a"])
        pool.return_back(b)
        assert got == [EventType.SKILL_RETURNED]

    def test_with_borrowed_context_manager(self):
        pool = SkillPool()
        pool.register(FakeSkill("a"))
        with Borrowed(pool.checkout(["a"]), pool):
            assert pool.health_report()["a"]["refcount"] == 1
        # 退出后还了
        assert pool.health_report()["a"]["refcount"] == 0


# ── retire ─────────────────────────────────────────────────────────────

class TestRetire:
    def test_retire_removes_skill(self):
        pool = SkillPool()
        pool.register(FakeSkill("a"))
        pool.retire("a")
        assert not pool.is_available("a")
        with pytest.raises(SkillNotFoundError):
            pool.checkout(["a"])

    def test_retire_decrements_refcount_safely(self):
        """已 retire 但有 bundle 没还,还的时候 refcount 不能减成负数."""
        pool = SkillPool()
        pool.register(FakeSkill("a"))
        b = pool.checkout(["a"])
        pool.retire("a")  # 借出去后 retire
        pool.return_back(b)  # 不应炸
        assert pool.health_report().get("a", {}).get("refcount", 0) == 0


# ── 健康度 ─────────────────────────────────────────────────────────────

class TestHealthCheck:
    def test_health_report_initial(self):
        pool = SkillPool()
        pool.register(FakeSkill("a"))
        h = pool.health_report()
        assert "a" in h
        assert h["a"]["health"]["error_rate"] == 0.0

    def test_tick_health_counts_success(self):
        pool = SkillPool()
        pool.register(FakeSkill("a"))
        pool._tick_health()
        h = pool.health_report()["a"]["health"]
        assert h["success"] == 1
        assert h["error_rate"] == 0.0

    def test_tick_health_auto_retire_on_high_error(self):
        """连续失败超过阈值,自动 retire."""
        pool = SkillPool(health_error_threshold=0.3)
        pool.register(FakeSkill("a", fail_health=True))
        # 跑 5 次 tick,每次都失败
        for _ in range(5):
            pool._tick_health()
        # 失败率高,自动 retire
        assert not pool.is_available("a")

    def test_health_check_loop_runs(self):
        pool = SkillPool()
        pool.register(FakeSkill("a"))

        async def _run_and_count():
            task = asyncio.create_task(pool.health_check_loop(interval_s=0.01))
            await asyncio.sleep(0.15)  # 给多次 tick 时间
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return pool.health_report()["a"]["health"]["success"]

        success_count = asyncio.run(_run_and_count())
        # 至少跑过 2 次 tick
        assert success_count >= 2


# ── 并发安全 ──────────────────────────────────────────────────────────

class TestConcurrency:
    def test_concurrent_checkout_return(self):
        """10 个线程同时借/还,不丢引用计数."""
        pool = SkillPool()
        pool.register(FakeSkill("a"))
        errors: list[Exception] = []

        def worker():
            try:
                for _ in range(50):
                    b = pool.checkout(["a"])
                    pool.return_back(b)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, errors
        # 最终 refcount 必须回到 0
        assert pool.health_report()["a"]["refcount"] == 0
