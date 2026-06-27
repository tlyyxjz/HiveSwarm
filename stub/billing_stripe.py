"""StripeBilling stub — stripe.Charge 软依赖,按 token 计量.

生产替换: stub.billing_noop.NoopBilling → stub.billing_stripe.StripeBilling.
        Stripe 失败降级到本地累计缓存,后台异步 retry.

依赖: stripe (TYPE_CHECKING 软依赖).
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.billing import BillingMeter, UsageRecord

if TYPE_CHECKING:
    import stripe

_log = logging.getLogger(__name__)

# 1 token = $0.00002 → 1 分 = 50000 tokens. 公司合同可改.
_TOKEN_PRICE_CENTS = 0.00002


class StripeBilling(BillingMeter):
    """按 token 计量 + 写到 Stripe + 本地缓存 fallback.

    Args:
        api_key: Stripe secret key (sk_...)
        price_per_1k_tokens_cents: 单价 (cents/1k tokens)
        fallback_path: 离线缓存路径
    """

    def __init__(
        self,
        api_key: str,
        price_per_1k_tokens_cents: float = 2.0,
        fallback_path: str | Path = "logs/billing_stripe_fallback.jsonl",
    ) -> None:
        self._api_key = api_key
        self._price = price_per_1k_tokens_cents
        self._fallback = Path(fallback_path).expanduser()
        self._fallback.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._local_total_cents: dict[str, float] = {}
        self._connect()

    def _connect(self) -> None:
        try:
            import stripe  # type: ignore

            stripe.api_key = self._api_key
            _log.info("StripeBilling configured (api_key prefix=%s)", self._api_key[:7])
        except Exception as exc:
            _log.warning("stripe import failed, billing noop+local: %s", exc, exc_info=True)

    def _calc_cents(self, usage: UsageRecord) -> int:
        total_tokens = usage.input_tokens + usage.output_tokens
        return int(total_tokens / 1000 * self._price)

    def _record_local(self, usage: UsageRecord, cents: int) -> None:
        with self._lock:
            self._local_total_cents[usage.user_id] = self._local_total_cents.get(usage.user_id, 0.0) + cents
            try:
                with self._fallback.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "user_id": usage.user_id,
                        "skill": usage.skill_name,
                        "tokens": usage.input_tokens + usage.output_tokens,
                        "cents": cents,
                    }, ensure_ascii=False) + "\n")
            except Exception as exc:
                _log.warning("billing fallback write failed: %s", exc, exc_info=True)

    def record(self, usage: UsageRecord) -> None:
        """记一笔. 调 stripe.Charge.create,失败降级本地."""
        cents = self._calc_cents(usage)
        if cents <= 0:
            return
        try:
            import stripe  # type: ignore

            stripe.Charge.create(
                amount=cents,
                currency="usd",
                description=f"hiveswarm:{usage.user_id}:{usage.skill_name}",
                metadata={
                    "user_id": usage.user_id,
                    "skill": usage.skill_name,
                    "input_tokens": str(usage.input_tokens),
                    "output_tokens": str(usage.output_tokens),
                },
            )
        except Exception as exc:
            _log.warning("stripe charge failed, fallback local: %s", exc, exc_info=True)
            self._record_local(usage, cents)

    def usage_for(self, user_id: str, period: str = "month") -> int:
        """查本月用量 (cents). Stripe 没现成 API,读本地累计."""
        with self._lock:
            return int(self._local_total_cents.get(user_id, 0.0))