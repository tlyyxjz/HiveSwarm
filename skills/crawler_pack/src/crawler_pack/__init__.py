"""HiveSwarm skill pack: 通用爬虫.

提供 3 个 skill:
  - http_fetch:  HTTP GET 任意 URL
  - url_extract: 从 HTML 提取链接 (BeautifulSoup / 正则 fallback)
  - http_post:   HTTP POST 表单/JSON

便捷入口:
  - CrawlerSkill: 单入口包装, 默认执行 http_fetch

设计: 不绑定特定业务 (e.g. GitHub), 通用 HTTP 客户端.

用法:
    from crawler_pack import CrawlerSkill
    skill = CrawlerSkill()
    result = skill.run({"url": "https://example.com"})
"""
from __future__ import annotations

from typing import Any

from core.skill import Skill, SkillManifest
from .skills import (
    HttpFetchSkill,
    UrlExtractSkill,
    HttpPostSkill,
    register_all,
)


class CrawlerSkill(Skill):
    """单入口爬虫技能——默认执行 HTTP GET, 也支持 POST 和链接提取.

    输入: {"url": "...", "method": "GET"|"POST", "extract_links": bool}
    输出: {"ok": True, "status": 200, "body": "...", "links": [...]}
    """

    def __init__(self) -> None:
        super().__init__(SkillManifest(
            name="crawler",
            api_version="1.0",
            description="通用 HTTP 爬虫（GET/POST/链接提取）",
            tags=("crawl", "http"),
        ))

    def run(self, input_data: dict) -> dict:
        url = input_data.get("url")
        if not url:
            return {"ok": False, "error": "url 必填"}
        method = input_data.get("method", "GET").upper()
        extract = input_data.get("extract_links", False)

        if method == "POST":
            fetcher = HttpPostSkill()
        else:
            fetcher = HttpFetchSkill()
        result = fetcher.run(input_data)

        if extract and result.get("ok") and result.get("body"):
            extractor = UrlExtractSkill()
            links_result = extractor.run({"html": result["body"]})
            result["links"] = links_result.get("links", [])
            result["link_count"] = links_result.get("count", 0)
        return result


__version__ = "0.2.0"
__all__ = [
    "CrawlerSkill",
    "HttpFetchSkill", "UrlExtractSkill", "HttpPostSkill",
    "register_all",
]
