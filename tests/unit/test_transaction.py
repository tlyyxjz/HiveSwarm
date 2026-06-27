"""TaskTransaction 单元测试."""
from __future__ import annotations

import pytest

from core.brain import SubTask
from core.skill import Skill, SkillManifest
from layers.work.factory import AgentFactory
from layers.work.pool import SkillPool
from layers.work.transaction import TaskTransaction


class EchoSkill(Skill):
    def __init__(self, name: str) -> None:
        super().__init__(SkillManifest(name=name, api_version="1.0"))
        self.calls: list[dict] = []

    def run(self, input_data: dict) -> dict:
        self.calls.append(input_data)
        return {"echo": input_data, "by": self.manifest.name}


class FailSkill(Skill):
    def __init__(self, name: str) -> None:
        super().__init__(SkillManifest(name=name, api_version="1.0"))

    def run(self, input_data: dict) -> dict:
        raise RuntimeError(f"skill {self.manifest.name} boom")


def _make_pool_with(*skills: Skill) -> tuple[SkillPool, AgentFactory]:
    pool = SkillPool()
    for s in skills:
        pool.register(s)
    return pool, AgentFactory(pool)


# ── 基本流程 ─────────────────────────────────────────────────────────

class TestBasicFlow:
    def test_single_subtask_success(self):
        pool, factory = _make_pool_with(EchoSkill("a"))
        with TaskTransaction(pool, factory, "t1") as tx:
            r = tx.add(SubTask(sub_id="s1", intent="do", required_skills=("a",))).run({"x": 1})
        assert r.ok
        assert tx._result.all_ok
        assert tx._result.success_count == 1
        assert pool.health_report()["a"]["refcount"] == 0

    def test_multiple_subtasks_all_success(self):
        pool, factory = _make_pool_with(EchoSkill("a"), EchoSkill("b"))
        with TaskTransaction(pool, factory, "t1") as tx:
            tx.add(SubTask(sub_id="s1", intent="do", required_skills=("a",))).run({})
            tx.add(SubTask(sub_id="s2", intent="do", required_skills=("b",))).run({})
        assert tx._result.all_ok
        assert tx._result.success_count == 2
        assert pool.health_report()["a"]["refcount"] == 0
        assert pool.health_report()["b"]["refcount"] == 0


# ── 失败 + abort 行为 ────────────────────────────────────────────────

class TestFailureHandling:
    def test_first_failure_aborts_subsequent(self):
        pool, factory = _make_pool_with(EchoSkill("a"), FailSkill("b"))
        with TaskTransaction(pool, factory, "t1", abort_on_failure=True) as tx:
            tx.add(SubTask(sub_id="s1", intent="do", required_skills=("a",))).run({})
            tx.add(
                SubTask(sub_id="s2", intent="do", required_skills=("b",))
            ).run({})  # FailSkill 跑会炸
            tx.add(SubTask(sub_id="s3", intent="do", required_skills=("a",))).run({})  # 跳过
        assert tx._result.aborted
        assert tx._result.success_count == 1
        # s2 失败 + s3 跳过 = fail_count=2
        assert tx._result.fail_count == 2
        # s3 跳过也记一条
        assert len(tx._result.results) == 3
        assert tx._result.results[2].error and "skipped" in tx._result.results[2].error
        # s2 是真失败,error 含 "boom"
        assert "boom" in tx._result.results[1].error
        # 借出去的全还
        assert pool.health_report()["a"]["refcount"] == 0
        assert pool.health_report()["b"]["refcount"] == 0

    def test_no_abort_continues_after_failure(self):
        pool, factory = _make_pool_with(EchoSkill("a"))
        with TaskTransaction(pool, factory, "t1", abort_on_failure=False) as tx:
            # 没注册 b,这个会失败
            tx.add(SubTask(sub_id="s1", intent="do", required_skills=("b",))).run({})
            # 这个还会跑
            tx.add(SubTask(sub_id="s2", intent="do", required_skills=("a",))).run({})
        assert not tx._result.aborted
        assert tx._result.success_count == 1
        assert tx._result.fail_count == 1

    def test_skill_runtime_error_counted_as_failure(self):
        pool, factory = _make_pool_with(FailSkill("f"))
        with TaskTransaction(pool, factory, "t1") as tx:
            r = tx.add(SubTask(sub_id="s1", intent="do", required_skills=("f",))).run({})
        assert not r.ok
        assert "boom" in r.error
        # 归还了
        assert pool.health_report()["f"]["refcount"] == 0


# ── 异常退出仍清理 ─────────────────────────────────────────────────

class TestExceptionPath:
    def test_exception_in_subtask_loop_still_returns_skills(self):
        pool, factory = _make_pool_with(EchoSkill("a"))
        try:
            with TaskTransaction(pool, factory, "t1") as tx:
                tx.add(SubTask(sub_id="s1", intent="do", required_skills=("a",))).run({})
                raise ValueError("boom")
        except ValueError:
            pass
        # 借的 a 已还
        assert pool.health_report()["a"]["refcount"] == 0

    def test_use_outside_with_raises(self):
        pool, factory = _make_pool_with(EchoSkill("a"))
        tx = TaskTransaction(pool, factory, "t1")
        with pytest.raises(RuntimeError, match="with block"):
            tx.add(SubTask(sub_id="s1", intent="do", required_skills=("a",)))


# ── 多次使用 ───────────────────────────────────────────────────────

class TestReuse:
    def test_transaction_result_accumulates(self):
        pool, factory = _make_pool_with(EchoSkill("a"), EchoSkill("b"))
        tx = TaskTransaction(pool, factory, "t1")
        with tx:
            tx.add(SubTask(sub_id="s1", intent="do", required_skills=("a",))).run({})
            tx.add(SubTask(sub_id="s2", intent="do", required_skills=("b",))).run({})
        # 退 tx 后结果还在(可查询)
        assert tx._result.success_count == 2
        assert tx._result.task_id == "t1"
