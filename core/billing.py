"""BillingMeter — 计费 ABC.

职责:按 token / 任务 / 技能调用次数 计量. MVP noop,公司里接 Stripe
计费. **关键**:不能让计量失败阻塞业务,失败要降级.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class UsageRecord:
    """一次资源使用. frozen 保证哈希稳定,可做幂等去重."""

    user_id: str
    skill_name: str
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0


class BillingMeter(ABC):
    """计量. 失败降级本地缓存,后台异步 flush."""

    @abstractmethod
    def record(self, usage: UsageRecord) -> None:
        """记一笔用量."""

    @abstractmethod
    def usage_for(self, user_id: str, period: str = "month") -> int:
        """查用量(分/月). 返回分(美元分/人民币分)."""
