"""crawler_pack unit tests — 通用 HTTP skill."""
from __future__ import annotations

import pytest
import sys
from pathlib import Path

# 添加 crawler_pack 到 path (跟 agentvet_pack 一致)
SKILL_SRC = Path(__file__).parent.parent.parent / "skills" / "crawler_pack" / "src"
sys.path.insert(0, str(SKILL_SRC))

from crawler_pack.skills import (  # noqa: E402
    HttpFetchSkill, UrlExtractSkill, HttpPostSkill,
    register_all,
)
from layers.work.pool import SkillPool  # noqa: E402


class TestHttpFetchSkill:
    def test_manifest(self):
        s = HttpFetchSkill()
        assert s.manifest.name == "http_fetch"
        assert s.manifest.api_version == "1.0"
        assert "http" in s.manifest.tags

    def test_missing_url_returns_error(self):
        s = HttpFetchSkill()
        r = s.run({})
        assert r["ok"] is False
        assert "url" in r["error"]


class TestUrlExtractSkill:
    def test_manifest(self):
        s = UrlExtractSkill()
        assert s.manifest.name == "url_extract"

    def test_extract_links_from_html_string(self):
        """纯字符串 HTML, 无需网络."""
        s = UrlExtractSkill()
        r = s.run({"html": '<a href="x">y</a><a href="z">w</a>'})
        assert r["ok"] is True
        assert r["count"] == 2
        hrefs = {link["href"] for link in r["links"]}
        assert hrefs == {"x", "z"}

    def test_missing_html_and_url_returns_error(self):
        s = UrlExtractSkill()
        r = s.run({})
        assert r["ok"] is False


class TestHttpPostSkill:
    def test_manifest(self):
        s = HttpPostSkill()
        assert s.manifest.name == "http_post"

    def test_missing_url_returns_error(self):
        s = HttpPostSkill()
        r = s.run({"data": {"k": "v"}})
        assert r["ok"] is False
        assert "url" in r["error"]


class TestRegisterAll:
    def test_register_all_into_pool(self):
        """3 个 skill 都注册到 pool."""
        pool = SkillPool()
        n = register_all(pool)
        assert n == 3
        names = set(pool.list_available())
        assert {"http_fetch", "url_extract", "http_post"} == names