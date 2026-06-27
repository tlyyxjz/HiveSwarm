"""SkillPool — 技能池 (注册 / 借出 / 归还 / 引用计数 / 健康度).

核心数据流:
  register(skill)              → 进池
  checkout(["a", "b"])         → 返回 SkillBundle,引用计数+1
  return_back(bundle)          → 引用计数-1,真还
  retire(name)                 → 下架健康度低的
  health_check_loop() async    → 后台巡检

并发: dict + threading.Lock 保护. 借还都是 O(1) 操作,瓶颈在 IO 不在锁.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING

from core.skill import Skill, SkillHealth
from core.skill_bundle import SkillBundle

if TYPE_CHECKING:
    from core.events import EventBus, EventType

_log = logging.getLogger(__name__)


class SkillNotFoundError(KeyError):
    """借不存在的技能,清晰报错."""


class SkillRetiredError(RuntimeError):
    """借已下架技能."""


class SkillPool:
    """线程安全的技能池."""

    def __init__(
        self,
        bus: "EventBus | None" = None,
        *,
        max_concurrent_per_skill: int = 100,
        health_error_threshold: float = 0.5,
    ) -> None:
        self._skills: dict[str, Skill] = {}
        self._refcount: dict[str, int] = {}
        self._health: dict[str, SkillHealth] = {}
        self._lock = threading.Lock()
        self._bus = bus
        self._max_concurrent = max_concurrent_per_skill
        self._health_threshold = health_error_threshold
        self._check_task: asyncio.Task | None = None

    # ── 注册 ─────────────────────────────────────────────────────────────

    def register(self, skill: Skill) -> None:
        """注册一个技能. 同名覆盖,引用计数保留(等于重置)."""
        name = skill.manifest.name
        with self._lock:
            self._skills[name] = skill
            self._refcount.setdefault(name, 0)
            self._health[name] = SkillHealth(name=name)
        _log.info("skill registered: %s (api=%s)", name, skill.manifest.api_version)

    def retire(self, name: str) -> None:
        """下架技能(健康度不达标时自动调)."""
        with self._lock:
            self._skills.pop(name, None)
            self._refcount.pop(name, None)
            self._health.pop(name, None)
        _log.warning("skill retired: %s", name)

    def list_available(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._skills.keys())

    def is_available(self, name: str) -> bool:
        with self._lock:
            return name in self._skills

    def get_manifest(self, name: str) -> dict | None:
        """获取技能的 manifest 信息."""
        with self._lock:
            skill = self._skills.get(name)
            if skill is None:
                return None
            return {
                "name": skill.manifest.name,
                "api_version": skill.manifest.api_version,
                "description": skill.manifest.description,
                "tags": skill.manifest.tags,
            }

    # ── 借 ───────────────────────────────────────────────────────────────

    def checkout(self, names: list[str]) -> SkillBundle:
        """借一组技能. 缺一个就全失败(原子性)."""
        with self._lock:
            for n in names:
                if n not in self._skills:
                    raise SkillNotFoundError(f"skill not in pool: {n!r}, available: {list(self._skills)}")
                if self._refcount[n] >= self._max_concurrent:
                    raise SkillRetiredError(
                        f"skill {n!r} hit concurrent limit: {self._max_concurrent}"
                    )
            # 全部 OK 才 +1
            skills = [self._skills[n] for n in names]
            for n in names:
                self._refcount[n] += 1

        bundle = SkillBundle(skills)
        self._emit_checkout(bundle)
        return bundle

    # ── 还 ───────────────────────────────────────────────────────────────

    def return_back(self, bundle: SkillBundle) -> None:
        """归还技能. 引用计数-1,已还报错."""
        if bundle.is_returned:
            raise RuntimeError(f"bundle already returned: {bundle.names!r}")
        with self._lock:
            for s in bundle.skills:
                name = s.manifest.name
                # 即便技能已被 retire, refcount 还是要减
                self._refcount[name] = max(0, self._refcount.get(name, 0) - 1)
            bundle.mark_returned()
        self._emit_return(bundle)

    # ── 健康度 ──────────────────────────────────────────────────────────

    async def health_check_loop(self, interval_s: float = 60.0) -> None:
        """后台巡检. 健康度低于阈值的自动 retire. 跑不停直到 task cancel."""
        while True:
            try:
                await self._tick_health_async()
            except Exception:  # noqa: BLE001
                _log.exception("health check tick failed")
            await asyncio.sleep(interval_s)

    async def _tick_health_async(self) -> None:
        """异步版 tick,跑在 event loop 内,直接 await 协程."""
        for name in list(self._skills):
            skill = self._skills[name]
            try:
                h = await skill.health_check()
            except Exception as exc:  # noqa: BLE001
                h = SkillHealth(name=name, last_error=str(exc))
                h.failure_count += 1
            with self._lock:
                old = self._health.get(name, SkillHealth(name=name))
                self._health[name] = SkillHealth(
                    name=name,
                    success_count=old.success_count + h.success_count,
                    failure_count=old.failure_count + h.failure_count,
                    last_check_ts=h.last_check_ts or 0.0,
                    last_error=h.last_error or old.last_error,
                )
                if self._health[name].error_rate > self._health_threshold:
                    self._skills.pop(name, None)
                    _log.warning("auto-retired %s (error rate high)", name)

    def _tick_health(self) -> None:
        """同步版 tick,供单测调用. 内部临时 event loop 跑协程.

        协程必须显式 await/close 一次,否则 leave coroutine 警告.
        """
        for name in list(self._skills):
            skill = self._skills[name]
            coro = skill.health_check()
            try:
                loop = asyncio.new_event_loop()
                try:
                    h = loop.run_until_complete(coro)
                finally:
                    loop.close()
            except Exception as exc:  # noqa: BLE001
                h = SkillHealth(name=name, last_error=str(exc))
                h.failure_count += 1
            with self._lock:
                old = self._health.get(name, SkillHealth(name=name))
                self._health[name] = SkillHealth(
                    name=name,
                    success_count=old.success_count + h.success_count,
                    failure_count=old.failure_count + h.failure_count,
                    last_check_ts=h.last_check_ts or 0.0,
                    last_error=h.last_error or old.last_error,
                )
                if self._health[name].error_rate > self._health_threshold:
                    self._skills.pop(name, None)
                    _log.warning("auto-retired %s (error rate high)", name)

    def health_report(self) -> dict[str, dict]:
        """快照,给 dashboard 用."""
        with self._lock:
            return {
                name: {
                    "refcount": self._refcount.get(name, 0),
                    "health": {
                        "success": h.success_count,
                        "failure": h.failure_count,
                        "error_rate": h.error_rate,
                        "last_error": h.last_error,
                    },
                }
                for name, h in self._health.items()
            }

    # ── 事件 ─────────────────────────────────────────────────────────────

    def _emit_checkout(self, bundle: SkillBundle) -> None:
        if self._bus is None:
            return
        try:
            from core.events import Event, EventType
            self._bus.publish(
                Event(type=EventType.SKILL_CHECKED_OUT, payload={"names": list(bundle.names)})
            )
        except Exception:  # noqa: BLE001
            _log.warning("emit checkout event failed", exc_info=True)

    def _emit_return(self, bundle: SkillBundle) -> None:
        if self._bus is None:
            return
        try:
            from core.events import Event, EventType
            self._bus.publish(
                Event(type=EventType.SKILL_RETURNED, payload={"names": list(bundle.names)})
            )
        except Exception:  # noqa: BLE001
            _log.warning("emit return event failed", exc_info=True)
