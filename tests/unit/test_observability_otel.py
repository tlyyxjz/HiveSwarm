"""Tests for stub.observability_otel.OTelTracer.

Mock tracer provider, 验 span 创建 / 上下文管理 / 异常标记.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from stub.observability_otel import OTelTracer


def test_stub_implements_abc():
    from core.telemetry import Tracer

    assert set(Tracer.__abstractmethods__) <= set(dir(OTelTracer))


def test_span_yields_normally_when_no_otel_sdk():
    """OTel SDK 未装 → span 走降级 buffer,正常 yield."""
    tracer = OTelTracer(service_name="test-svc", recent_buffer_size=10)
    tracer._ot_tracer = None

    with tracer.span("op", user="alice"):
        pass

    spans = tracer.recent_spans()
    assert len(spans) == 1
    assert spans[0]["name"] == "op"
    assert spans[0]["attrs"]["user"] == "alice"
    assert spans[0]["status"] == "ok"


def test_span_records_exception_when_error_in_fallback_mode():
    """降级模式: 块内抛异常 → buffer 记录 error status."""
    tracer = OTelTracer(service_name="test-svc")
    tracer._ot_tracer = None

    with pytest.raises(RuntimeError, match="boom"):
        with tracer.span("op.fail"):
            raise RuntimeError("boom")

    spans = tracer.recent_spans()
    assert len(spans) == 1
    assert spans[0]["status"] == "error"
    assert "boom" in spans[0]["error"]


def test_span_uses_otel_sdk_when_available():
    """OTel SDK 可用 → 走 SDK span 路径."""
    tracer = OTelTracer(service_name="test-svc")
    mock_ot = MagicMock()
    mock_span = MagicMock()
    mock_ot.start_as_current_span.return_value.__enter__.return_value = mock_span
    tracer._ot_tracer = mock_ot

    with tracer.span("sdk.op", kind="test"):
        pass

    mock_ot.start_as_current_span.assert_called_once_with("sdk.op", attributes={"kind": "test"})


def test_metric_inc_observe_are_noops():
    """metric API 不抛异常 (降级日志)."""
    tracer = OTelTracer(service_name="test-svc")
    tracer.metric_inc("req.count", value=3, endpoint="/api")
    tracer.metric_observe("latency", value_ms=42.5, endpoint="/api")
    # 没崩就是过