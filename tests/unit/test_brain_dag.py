"""MockBrain DAG plan tests — 通用模板."""
from __future__ import annotations

import asyncio

from layers.brain.planner import MockBrain


def _brain():
    return MockBrain()


class TestDAGCrawlChain:
    """通用模板: http_fetch → url_extract → (user-defined)"""

    def test_crawl_chain_triggers(self):
        """触发词: 抓/爬/fetch/crawl."""
        for kw in ("抓网页", "爬数据", "fetch url", "crawl site"):
            plan = asyncio.run(_brain().plan(kw))
            assert len(plan.subtasks) == 3, f"'{kw}' should trigger 3-subtask DAG"
            names = [s.required_skills[0] if s.required_skills else "none" for s in plan.subtasks]
            assert names[0] == "http_fetch"
            assert names[1] == "url_extract"

    def test_crawl_chain_dependencies(self):
        """依赖: extract 依赖 fetch, post-process 依赖 extract."""
        plan = asyncio.run(_brain().plan("fetch website"))
        deps = {s.sub_id: s.depends_on for s in plan.subtasks}
        assert deps["s1"] == ()
        assert deps["s2"] == ("s1",)
        assert deps["s3"] == ("s2",)

    def test_dag_no_cycles(self):
        plan = asyncio.run(_brain().plan("抓数据"))
        for sub in plan.subtasks:
            for dep in sub.depends_on:
                assert dep < sub.sub_id, f"{sub.sub_id} 依赖 {dep} 但 {dep} 在它之后"


class TestBackwardCompatibility:
    """原有 plan() 行为不破坏."""

    def test_ppt_still_works(self):
        plan = asyncio.run(_brain().plan("帮我做一个 PPT"))
        names = [s.required_skills[0] if s.required_skills else "none" for s in plan.subtasks]
        assert "data_collect" in names
        assert "outline" in names

    def test_scan_still_works(self):
        plan = asyncio.run(_brain().plan("扫描这个项目"))
        names = [s.required_skills[0] if s.required_skills else "none" for s in plan.subtasks]
        assert "agentvet_l1" in names

    def test_unknown_still_works(self):
        plan = asyncio.run(_brain().plan("hello world"))
        assert len(plan.subtasks) >= 1


class TestRationale:
    def test_crawl_rationale_mentions_chain(self):
        plan = asyncio.run(_brain().plan("fetch data"))
        assert "chain" in plan.rationale.lower() or "fetch" in plan.rationale.lower()