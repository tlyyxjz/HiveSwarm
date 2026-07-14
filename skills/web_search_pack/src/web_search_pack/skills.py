"""WebSearchSkill — 全网搜索 (DuckDuckGo HTML, 无需 API key).

输入: {"query": "关键词", "max_results": 10 (可选, 默认 10)}
输出: {"query": ..., "count": N, "results": [{"title", "url", "snippet"}]}

降级: 网络不通时返回 {"results": [], "error": "...", "count": 0}
"""
from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import unquote

import httpx

from core.skill import Skill, SkillManifest, SkillHealth

_log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class WebSearchSkill(Skill):
    """全网搜索. 调用 DuckDuckGo HTML 接口."""

    def __init__(self, timeout: float = 10.0) -> None:
        super().__init__(SkillManifest(
            name="web_search",
            api_version="1.0",
            description="DuckDuckGo HTML search, no API key needed",
            tags=("web", "search", "internet"),
        ))
        self._timeout = timeout

    def run(self, input_data: dict) -> dict:
        query = (input_data.get("query") or "").strip()
        if not query:
            return {"results": [], "count": 0, "error": "query is empty"}

        max_results = int(input_data.get("max_results", 10))
        max_results = max(1, min(max_results, 30))  # 限 1-30

        try:
            html = asyncio.run(self._fetch(query))
            results = self._parse(html)[:max_results]
            return {
                "query": query,
                "count": len(results),
                "results": results,
            }
        except Exception as exc:  # noqa: BLE001
            _log.warning("web_search failed for query=%r: %s", query, exc)
            return {
                "query": query,
                "count": 0,
                "results": [],
                "error": str(exc),
            }

    async def _fetch(self, query: str) -> str:
        async with httpx.AsyncClient(
            timeout=self._timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query, "kl": "us-en"},
            )
            resp.raise_for_status()
            return resp.text

    def _parse(self, html: str) -> list[dict]:
        """极简解析 DuckDuckGo HTML 结果.

        真实 DDG HTML 结构复杂, 这里用 regex 抓 title/url/snippet 三件套.
        抗结构变动能力弱 — 失败时返回空列表, 不抛.
        """
        results: list[dict] = []
        # 抓 result__a 链接 + 文本
        link_pattern = re.compile(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            re.DOTALL,
        )
        snippet_pattern = re.compile(
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
            re.DOTALL,
        )

        for match in link_pattern.finditer(html):
            raw_url = match.group(1)
            raw_title = self._strip_html(match.group(2))

            # DuckDuckGo 把外部 URL 包在 /l/?uddg=<encoded> 里
            url = self._extract_real_url(raw_url)

            # snippet 在 link 之后
            snippet = ""
            snip_match = snippet_pattern.search(html, match.end())
            if snip_match:
                snippet = self._strip_html(snip_match.group(1))

            if not url or not raw_title:
                continue

            results.append({
                "title": raw_title,
                "url": url,
                "snippet": snippet[:200],  # 截断
            })
        return results

    @staticmethod
    def _extract_real_url(raw_url: str) -> str:
        """DDG 跳转 URL 提取真实地址."""
        if "uddg=" in raw_url:
            m = re.search(r"uddg=([^&]+)", raw_url)
            if m:
                return unquote(m.group(1))
        return raw_url

    @staticmethod
    def _strip_html(text: str) -> str:
        return re.sub(r"<[^>]+>", "", text).strip()

    async def health_check(self) -> SkillHealth:
        """健康: 能 fetch 到任何内容就算 ok."""
        try:
            await self._fetch("test")
            return SkillHealth(name=self.manifest.name, success_count=1)
        except Exception as exc:  # noqa: BLE001
            return SkillHealth(name=self.manifest.name, last_error=str(exc))