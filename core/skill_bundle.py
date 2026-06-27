"""SkillBundle + Borrowed — 借/还的事务对象.

核心创新(相对 AutoGen/CrewAI):
  技能不是永久绑在 Agent 上的,而是从 Pool 借出来打包成 Bundle,
  用完强制归还. Borrowed 是 contextmanager,异常自动归还,杜绝泄漏.

数据流:
  Pool.checkout(["a", "b"]) → SkillBundle(skills=[a, b], refs=2)
      ↓
  with Borrowed(bundle, pool) as b:
      agent = factory.assemble(skills=b.skills)
      agent.run(task)        # 任务跑
  # __exit__ 调 pool.return_back(bundle) 强制还
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from types import TracebackType
from typing import TYPE_CHECKING, Protocol

from core.skill import Skill

if TYPE_CHECKING:
    pass


class SkillBundle:
    """借出来的技能包. 不可变,引用计数自带."""

    __slots__ = ("skills", "ref_count", "_returned")

    def __init__(self, skills: list[Skill]) -> None:
        self.skills: list[Skill] = list(skills)  # 拷贝防外部改
        self.ref_count: int = len(skills)  # 引用计数 = 技能数
        self._returned: bool = False

    @property
    def is_returned(self) -> bool:
        return self._returned

    @property
    def names(self) -> tuple[str, ...]:
        """借了哪些技能名(给日志 / 事件用)."""
        return tuple(s.manifest.name for s in self.skills)

    def mark_returned(self) -> None:
        """Pool 调这个,标记已还. 二次还就报错."""
        if self._returned:
            raise RuntimeError(f"bundle already returned: {self.names}")
        self._returned = True

    def __repr__(self) -> str:
        state = "returned" if self._returned else "live"
        return f"SkillBundle(names={self.names!r}, state={state})"


class Borrowed(AbstractContextManager["SkillBundle"]):
    """借/还事务. with 块结束(正常/异常)自动归还.

    用法:
        bundle = pool.checkout(["scan_l1", "fetch"])
        with Borrowed(bundle, pool) as b:
            agent = factory.assemble(skills=b.skills)
            result = agent.run(task)
        # 自动 pool.return_back(bundle),即使上面抛了异常
    """

    def __init__(self, bundle: SkillBundle, pool: SkillPoolPort) -> None:
        self._bundle = bundle
        self._pool = pool

    def __enter__(self) -> SkillBundle:
        if self._bundle.is_returned:
            raise RuntimeError(f"cannot borrow returned bundle: {self._bundle.names!r}")
        return self._bundle

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # 已还过就 noop(允许 transaction 二次清理)
        if self._bundle.is_returned:
            return
        # 不管正常还是异常,都尝试归还. 归还本身报错 → 压成 warning,不掩盖主异常.
        try:
            self._pool.return_back(self._bundle)
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).warning(
                "failed to return bundle %s", self._bundle.names, exc_info=True
            )
        # 不抑制异常(exc_type is None 透传),让外层 try/except 处理
        return None
