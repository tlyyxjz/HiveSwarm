"""PermanentRetention 单测 — 合规相关 stub."""
from __future__ import annotations

import pytest

from stub.governance_permanent import PermanentRetention, _PII_SENTINEL


@pytest.fixture
def retention() -> PermanentRetention:
    return PermanentRetention()


# ── should_retain ────────────────────────────────────────────

class TestShouldRetain:
    def test_always_true_for_fresh(self, retention: PermanentRetention) -> None:
        assert retention.should_retain({"x": 1}, age_days=0) is True

    def test_always_true_for_old(self, retention: PermanentRetention) -> None:
        """MVP: 永不删, 即便 100 年."""
        assert retention.should_retain({"x": 1}, age_days=365 * 100) is True

    def test_always_true_for_empty_record(self, retention: PermanentRetention) -> None:
        assert retention.should_retain({}, age_days=99999) is True


# ── scrub_pii: 邮箱 ─────────────────────────────────────────

class TestScrubEmail:
    def test_simple_email(self, retention: PermanentRetention) -> None:
        assert "alice@example.com" not in retention.scrub_pii("contact alice@example.com today")
        assert _PII_SENTINEL in retention.scrub_pii("contact alice@example.com today")

    def test_email_with_subdomain(self, retention: PermanentRetention) -> None:
        out = retention.scrub_pii("user@mail.corp.example.com")
        assert "user@" not in out

    def test_email_with_plus(self, retention: PermanentRetention) -> None:
        out = retention.scrub_pii("send to alice+test@example.com please")
        assert "alice+" not in out

    def test_multiple_emails(self, retention: PermanentRetention) -> None:
        out = retention.scrub_pii("a@x.com and b@y.com")
        assert out.count(_PII_SENTINEL) == 2


# ── scrub_pii: 中国手机号 ───────────────────────────────────

class TestScrubPhone:
    def test_standard_mobile(self, retention: PermanentRetention) -> None:
        out = retention.scrub_pii("call 13800138000 now")
        assert "13800138000" not in out
        assert _PII_SENTINEL in out

    def test_various_carriers(self, retention: PermanentRetention) -> None:
        for num in ["13012345678", "15612345678", "18812345678", "19912345678"]:
            out = retention.scrub_pii(f"phone {num}")
            assert num not in out

    def test_non_mobile_not_scrubbed(self, retention: PermanentRetention) -> None:
        """非 1[3-9] 开头的不应被脱敏 (避免误伤)."""
        out = retention.scrub_pii("order 12345678")
        assert "12345678" in out  # 没动

    def test_short_number_not_scrubbed(self, retention: PermanentRetention) -> None:
        out = retention.scrub_pii("pin 1380013")
        assert "1380013" in out


# ── scrub_pii: 身份证 ──────────────────────────────────────

class TestScrubIDCard:
    def test_18_digit_id(self, retention: PermanentRetention) -> None:
        id_18 = "110101199003078811"
        out = retention.scrub_pii(f"id {id_18}")
        assert id_18 not in out

    def test_18_digit_with_X(self, retention: PermanentRetention) -> None:
        id_x = "11010119900307881X"
        out = retention.scrub_pii(f"id {id_x}")
        assert id_x not in out

    def test_short_id_not_scrubbed(self, retention: PermanentRetention) -> None:
        out = retention.scrub_pii("serial 11010119900307")
        assert "11010119900307" in out


# ── scrub_pii: 组合 / 边界 ─────────────────────────────────

class TestScrubMixed:
    def test_email_and_phone_in_one(self, retention: PermanentRetention) -> None:
        text = "联系 alice@example.com 或 13800138000"
        out = retention.scrub_pii(text)
        assert "alice@" not in out
        assert "13800138000" not in out
        assert out.count(_PII_SENTINEL) == 2

    def test_no_pii_returns_original(self, retention: PermanentRetention) -> None:
        text = "今天天气不错，没什么敏感信息"
        assert retention.scrub_pii(text) == text

    def test_empty_string(self, retention: PermanentRetention) -> None:
        assert retention.scrub_pii("") == ""

    def test_unicode_preserved(self, retention: PermanentRetention) -> None:
        """脱敏不应影响其他中文."""
        out = retention.scrub_pii("用户张三说：邮箱 zhang@example.com")
        assert "用户张三说：" in out
        assert "zhang@" not in out

    def test_idempotent(self, retention: PermanentRetention) -> None:
        """对已脱敏文本再脱敏不应改变."""
        once = retention.scrub_pii("alice@example.com")
        twice = retention.scrub_pii(once)
        assert once == twice