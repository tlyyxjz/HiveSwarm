"""TaskTransaction — 一笔任务的事务包装.

对外一个 with 块搞定全部:
  with TaskTransaction(pool, factory) as tx:
      tx.run_subtask(sub1)
      tx.run_subtask(sub2)   # 前一个失败就跳

特性:
  - 任何 subtask 失败, 后续 subtask 跳过(可选), 已借的全还
  - 收集所有结果, 失败信息完整
  - 上下文管理器保证不泄漏
"""
from __future__ import annotations

import logging
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any

from core.brain import SubTask
from layers.work.factory import AgentFactory
from layers.work.pool import SkillPool

_log = logging.getLogger(__name__)


@dataclass
class SubTaskResult:
    """单个 subtask 的结果."""

    sub_id: str
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class TransactionResult:
    """整笔事务的结果汇总."""

    task_id: str = ""
    results: list[SubTaskResult] = field(default_factory=list)
    success_count: int = 0
    fail_count: int = 0
    aborted: bool = False  # 失败时是否中断后续 subtask

    @property
    def all_ok(self) -> bool:
        return self.fail_count == 0 and not self.aborted


class TaskTransaction(AbstractContextManager["TaskTransaction"]):
    """一笔任务的事务.

    用法:
        with TaskTransaction(pool, factory, task_id="t1") as tx:
            tx.add(sub1).run({"x": 1})
            tx.add(sub2).run({"y": 2})
        # 自动清理所有借出的 bundle
    """

    def __init__(
        self,
        pool: SkillPool,
        factory: AgentFactory,
        task_id: str = "",
        *,
        abort_on_failure: bool = True,
    ) -> None:
        self._pool = pool
        self._factory = factory
        self._task_id = task_id or f"tx-{id(self):x}"
        self._abort = abort_on_failure
        self._borrows: list = []  # Borrowed 们, 退出时统一清理
        self._result = TransactionResult(task_id=self._task_id)
        self._entered = False

    def __enter__(self) -> "TaskTransaction":
        self._entered = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # 不管异常,归还所有借出的技能
        for b in self._borrows:
            try:
                b.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                _log.warning("failed to return borrow on transaction exit", exc_info=True)
        self._borrows.clear()
        return None

    def _add_result(self, r: SubTaskResult) -> None:
        self._result.results.append(r)
        if r.ok:
            self._result.success_count += 1
        else:
            self._result.fail_count += 1
            if self._abort:
                self._result.aborted = True

    def add(self, subtask: SubTask) -> "SubtaskRunner":
        """加一个 subtask, 返回 SubtaskRunner 让用户调 run()."""
        if not self._entered:
            raise RuntimeError("TaskTransaction must be used in a with block")
        return SubtaskRunner(self, subtask)


class SubtaskRunner:
    """单个 subtask 的执行句柄. 调 run(input) 跑一次."""

    def __init__(self, tx: TaskTransaction, subtask: SubTask) -> None:
        self._tx = tx
        self._subtask = subtask

    def run(self, input_data: dict[str, Any]) -> SubTaskResult:
        """跑这个 subtask. 内部: 借 → 装 → 跑 → 销毁 → 归还."""
        if self._tx._result.aborted:
            # 上一轮失败 + abort=True, 直接跳过
            r = SubTaskResult(
                sub_id=self._subtask.sub_id, ok=False, error="skipped (previous failure)"
            )
            self._tx._add_result(r)
            return r

        try:
            agent, borrowed = self._tx._factory.assemble(self._subtask)
            self._tx._borrows.append(borrowed)
            with borrowed:
                import asyncio

                raw = asyncio.run(
                    agent.run({"input": input_data, "intent": self._subtask.intent})
                )
                agent.destroy()

            if raw.get("ok"):
                r = SubTaskResult(sub_id=self._subtask.sub_id, ok=True, result=raw)
            else:
                r = SubTaskResult(
                    sub_id=self._subtask.sub_id,
                    ok=False,
                    result=raw,
                    error=raw.get("error", "unknown"),
                )
            self._tx._add_result(r)
            return r
        except Exception as exc:  # noqa: BLE001
            r = SubTaskResult(
                sub_id=self._subtask.sub_id, ok=False, error=f"assembly failed: {exc}"
            )
            self._tx._add_result(r)
            return r

    @property
    def transaction_result(self) -> TransactionResult:
        return self._tx._result
