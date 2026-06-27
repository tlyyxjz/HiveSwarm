"""PermanentRetention — MVP 永远保留 + 不脱敏. 公司用换 DLP 时改 1 行."""
from __future__ import annotations

import re
from typing import Any

from core.governance import DataRetention

# MVP 脱敏规则 = 直接返回原文(显示 "not implemented in MVP" 哨兵)
_PII_SENTINEL = "[MVP-NO-SCRUB]"

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_PHONE_RE = re.compile(r"\b1[3-9]\d{9}\b")  # 中国手机号
_ID_RE = re.compile(r"\b\d{17}[\dXx]\b")    # 身份证


class PermanentRetention(DataRetention):
    """MVP: 啥都保留,啥都不脱敏(返回哨兵提示)."""

    def should_retain(self, record: dict[str, Any], age_days: int) -> bool:
        return True  # 永不删

    def scrub_pii(self, text: str) -> str:
        # MVP 跑通:真做正则脱敏,但用哨兵标记(便于后面看哪些需要真脱)
        out = _EMAIL_RE.sub(_PII_SENTINEL, text)
        out = _PHONE_RE.sub(_PII_SENTINEL, out)
        out = _ID_RE.sub(_PII_SENTINEL, out)
        return out
