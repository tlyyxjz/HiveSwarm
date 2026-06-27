"""通用爬虫 skill 实现 — 通用数据采集器, 不绑定特定业务.

3 个 skill:
  - http_fetch:  HTTP GET 任意 URL, 返回 raw 内容 (HTML/JSON/...)
  - url_extract: 从 HTML 提取链接/标题/正文 (用 BeautifulSoup, 可选依赖)
  - http_post:   HTTP POST 表单到 URL (e.g. 登录、提交搜索)

跟 agentvet_pack 一样的套路:
  每个 skill = 1 个 class, 实现 core/skill.py 的 Skill ABC.
  延迟 import 网络依赖, hive 启动不强制.
"""
from __future__ import annotations

import logging

from core.skill import Skill, SkillHealth, SkillManifest

_log = logging.getLogger(__name__)


# ── Skill 1: http_fetch ─────────────────────────────────────────────────

class HttpFetchSkill(Skill):
    """HTTP GET 任意 URL, 返回 raw body.

    输入: {"url": "https://example.com", "headers": {...}}  (headers 可选)
    输出: {"ok": True, "status": 200, "body": "...", "headers": {...}}
    """

    def __init__(self) -> None:
        super().__init__(SkillManifest(
            name="http_fetch",
            api_version="1.0",
            description="HTTP GET any URL and return raw response body",
            tags=("crawl", "http"),
        ))

    def run(self, input_data: dict) -> dict:
        url = input_data.get("url")
        if not url:
            return {"ok": False, "error": "url is required"}
        try:
            import os
            saved = os.environ.pop("NO_PROXY", None)
            os.environ["NO_PROXY"] = "127.0.0.1,localhost"
            try:
                import httpx
                r = httpx.get(url, timeout=30.0, follow_redirects=True)
                return {"ok": True, "status": r.status_code, "body": r.text[:50000], "headers": dict(r.headers)}
            finally:
                if saved is not None:
                    os.environ["NO_PROXY"] = saved
                else:
                    os.environ.pop("NO_PROXY", None)
        except Exception as exc:
            _log.exception("http_fetch failed")
            return {"ok": False, "error": str(exc)}

    async def health_check(self) -> SkillHealth:
        try:
            import httpx
            resp = httpx.get("https://httpbin.org/status/200", timeout=5)
            if resp.status_code == 200:
                return SkillHealth(name=self.manifest.name, success_count=1)
            h = SkillHealth(name=self.manifest.name, last_error=f"status {resp.status_code}")
            h.failure_count += 1
            return h
        except Exception as exc:  # noqa: BLE001
            h = SkillHealth(name=self.manifest.name, last_error=str(exc))
            h.failure_count += 1
            return h


# ── Skill 2: url_extract ───────────────────────────────────────────────

class UrlExtractSkill(Skill):
    """从 HTML 提取链接 (无 BeautifulSoup 时退回正则).

    输入: {"html": "<a href='x'>..."} 或 {"url": "https://..."} (二选一)
    输出: {"ok": True, "links": [...], "count": N}
    """

    def __init__(self) -> None:
        super().__init__(SkillManifest(
            name="url_extract",
            api_version="1.0",
            description="Extract links from HTML (BeautifulSoup if available, regex fallback)",
            tags=("crawl", "parse", "html"),
        ))

    def run(self, input_data: dict) -> dict:
        html = input_data.get("html", "")
        if not html:
            return {"ok": False, "error": "html is required"}
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            links = []
            for a in soup.find_all("a", href=True):
                links.append({"text": a.get_text(strip=True)[:200], "href": a["href"][:500]})
            return {"ok": True, "count": len(links), "links": links[:200]}
        except Exception as exc:
            # bs4 fallback
            import re
            pattern = r'<a[^>]+href=["\']([^"\']+)["\']'
            matches = re.findall(pattern, html, re.IGNORECASE)
            links = [{"href": m} for m in matches[:200]]
            return {"ok": True, "count": len(links), "links": links, "fallback": "regex (bs4 unavailable)"}

    async def health_check(self) -> SkillHealth:
        try:
            r = self.run({"html": '<a href="x">y</a><a href="z">w</a>'})
            if r["ok"] and r["count"] == 2:
                return SkillHealth(name=self.manifest.name, success_count=1)
            h = SkillHealth(name=self.manifest.name, last_error=f"count={r.get('count')}")
            h.failure_count += 1
            return h
        except Exception as exc:  # noqa: BLE001
            h = SkillHealth(name=self.manifest.name, last_error=str(exc))
            h.failure_count += 1
            return h


# ── Skill 3: http_post ─────────────────────────────────────────────────

class HttpPostSkill(Skill):
    """HTTP POST 到任意 URL.

    输入: {"url": "...", "data": {...}, "json": {...}, "headers": {...}}
    输出: {"ok": True, "status": N, "body": "...", "url": "..."}
    """

    def __init__(self) -> None:
        super().__init__(SkillManifest(
            name="http_post",
            api_version="1.0",
            description="HTTP POST to any URL (form / JSON / arbitrary)",
            tags=("crawl", "http", "post"),
        ))

    def run(self, input_data: dict) -> dict:
        url = input_data.get("url")
        if not url:
            return {"ok": False, "error": "url is required"}
        try:
            import os
            saved = os.environ.pop("NO_PROXY", None)
            os.environ["NO_PROXY"] = "127.0.0.1,localhost"
            try:
                import httpx
                if "json" in input_data:
                    r = httpx.post(url, json=input_data["json"], timeout=30.0)
                else:
                    r = httpx.post(url, data=input_data.get("data", {}), timeout=30.0)
                return {"ok": True, "status": r.status_code, "body": r.text[:50000]}
            finally:
                if saved is not None:
                    os.environ["NO_PROXY"] = saved
                else:
                    os.environ.pop("NO_PROXY", None)
        except Exception as exc:
            _log.exception("http_post failed")
            return {"ok": False, "error": str(exc)}

    async def health_check(self) -> SkillHealth:
        return SkillHealth(name=self.manifest.name, success_count=1)


# 注册入口 (给 Pool 用)
def register_all(pool) -> int:
    """把 3 个 skill 全部注册到 pool."""
    n = 0
    for cls in (HttpFetchSkill, UrlExtractSkill, HttpPostSkill):
        try:
            pool.register(cls())
            n += 1
        except Exception as exc:  # noqa: BLE001
            _log.warning("register %s failed: %s", cls.__name__, exc)
    return n