"""SkillBundle + Borrowed 单元测试.

覆盖:借/还 / 异常自动归还 / 引用计数 / 重复还报错 / with 块里异常透传.
"""
from __future__ import annotations

from typing import Any

import pytest

from core.skill import Skill, SkillManifest
from core.skill_bundle import Borrowed, SkillBundle


# ── 测试用 fake ──────────────────────────────────────────────────────────

class FakeSkill(Skill):
    """最小 Skill 实现,测试用."""

    def __init__(self, name: str) -> None:
        super().__init__(SkillManifest(name=name, api_version="1.0"))
        self.run_count = 0

    def run(self, input_data: dict) -> dict:
        self.run_count += 1
        return {"skill": self.manifest.name, "echo": input_data}


class FakePool:
    """最小 Pool,记录 return_back 次数."""

    def __init__(self) -> None:
        self.returned: list[SkillBundle] = []

    def return_back(self, bundle: SkillBundle) -> None:
        bundle.mark_returned()
        self.returned.append(bundle)


# ── SkillBundle ──────────────────────────────────────────────────────────

class TestSkillBundle:
    def test_create_binds_skills_and_refcount(self):
        a, b = FakeSkill("a"), FakeSkill("b")
        bundle = SkillBundle([a, b])
        assert bundle.ref_count == 2
        assert bundle.names == ("a", "b")
        assert bundle.is_returned is False

    def test_skills_copied_not_aliased(self):
        """外部 list 改不影响 bundle.skills."""
        original = [FakeSkill("a")]
        bundle = SkillBundle(original)
        original.append(FakeSkill("b"))  # 外部加
        assert len(bundle.skills) == 1  # bundle 不受影响

    def test_mark_returned(self):
        bundle = SkillBundle([FakeSkill("a")])
        bundle.mark_returned()
        assert bundle.is_returned is True
        # 再 mark 就报错
        with pytest.raises(RuntimeError, match="already returned"):
            bundle.mark_returned()


# ── Borrowed 正常路径 ────────────────────────────────────────────────────

class TestBorrowedHappyPath:
    def test_enter_returns_bundle(self):
        pool = FakePool()
        bundle = SkillBundle([FakeSkill("a")])
        with Borrowed(bundle, pool) as b:
            assert b is bundle
            assert not b.is_returned
        # 退出后归还
        assert bundle.is_returned is True
        assert pool.returned == [bundle]

    def test_skill_usable_inside_block(self):
        pool = FakePool()
        skill = FakeSkill("a")
        bundle = SkillBundle([skill])
        with Borrowed(bundle, pool):
            result = skill.run({"k": "v"})
            assert result == {"skill": "a", "echo": {"k": "v"}}
        assert skill.run_count == 1


# ── Borrowed 异常路径(关键) ──────────────────────────────────────────────

class TestBorrowedExceptionPath:
    def test_exception_inside_block_triggers_return(self):
        """with 块里抛异常,归还照样发生. 这就是 Borrowed 存在的意义."""
        pool = FakePool()
        bundle = SkillBundle([FakeSkill("a")])
        with pytest.raises(ValueError, match="boom"):
            with Borrowed(bundle, pool):
                raise ValueError("boom")
        # 即便任务炸,技能也还了
        assert bundle.is_returned is True
        assert pool.returned == [bundle]

    def test_exception_propagates_not_swallowed(self):
        """归还不能把主异常吞掉,用户该收的 ValueError 必须收到."""
        pool = FakePool()
        bundle = SkillBundle([FakeSkill("a")])
        caught: ValueError | None = None
        try:
            with Borrowed(bundle, pool):
                raise ValueError("original")
        except ValueError as e:
            caught = e
        assert caught is not None
        assert str(caught) == "original"

    def test_return_failure_does_not_swallow_original(self):
        """如果归还本身也炸了,主异常优先."""
        class BrokenPool:
            def return_back(self, bundle):
                raise RuntimeError("pool broken")

        bundle = SkillBundle([FakeSkill("a")])
        with pytest.raises(ValueError, match="primary"):
            with Borrowed(bundle, BrokenPool()):
                raise ValueError("primary")
        # BrokenPool 异常被吞(log warning),主异常透传


# ── 边界情况 ─────────────────────────────────────────────────────────────

class TestBorrowedEdgeCases:
    def test_empty_bundle(self):
        pool = FakePool()
        bundle = SkillBundle([])
        with Borrowed(bundle, pool) as b:
            assert b.skills == []
            assert b.ref_count == 0
        assert bundle.is_returned is True

    def test_enter_returned_bundle_raises(self):
        """已经归还的 bundle 不能再次 enter."""
        pool = FakePool()
        bundle = SkillBundle([FakeSkill("a")])
        with Borrowed(bundle, pool):
            pass
        # bundle 第一次借已归还
        with pytest.raises(RuntimeError, match="cannot borrow returned"):
            with Borrowed(bundle, pool):
                pass

    def test_repr(self):
        bundle = SkillBundle([FakeSkill("a"), FakeSkill("b")])
        r = repr(bundle)
        assert "a" in r and "b" in r
        assert "live" in r
        bundle.mark_returned()
        assert "returned" in repr(bundle)
