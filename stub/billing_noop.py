"""NoopBilling — 啥都不干,占位. 换 Stripe 时改 1 行配置."""
from __future__ import annotations

from core.billing import BillingMeter, UsageRecord


class NoopBilling(BillingMeter):
    """MVP: 不用真计费,所有用量返回 0. 接口已 stable."""

    def record(self, usage: UsageRecord) -> None:
        return  # 默默吞掉,接口稳定不报错

    def usage_for(self, user_id: str, period: str = "month") -> int:
        return 0
