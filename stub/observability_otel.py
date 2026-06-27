"""OpenTelemetry Tracer stub — opentelemetry-api 软依赖.

生产替换: stub.telemetry_noop.NoopTelemetry → stub.observability_otel.OTelTracer.
        真实 span 上报到 OTel collector,本地保留最近 N 条用于调试.

依赖: opentelemetry-api + opentelemetry-sdk (TYPE_CHECKING 软依赖).
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator

from core.telemetry import Tracer

if TYPE_CHECKING:
    from opentelemetry.trace import Tracer as OTelSDKTracer

_log = logging.getLogger(__name__)


class OTelTracer(Tracer):
    """OpenTelemetry 适配. 失败降级到本地环形缓冲.

    Args:
        service_name: 服务名 (resource attribute)
        endpoint: OTLP endpoint (实际部署时 SDK 配置传入)
        recent_buffer_size: 失败降级时本地保留 span 数
    """

    def __init__(
        self,
        service_name: str = "hiveswarm",
        endpoint: str | None = None,
        recent_buffer_size: int = 1000,
    ) -> None:
        self._service = service_name
        self._endpoint = endpoint
        self._buffer: deque[dict[str, Any]] = deque(maxlen=recent_buffer_size)
        self._lock = threading.Lock()
        self._ot_tracer: Any = None
        self._init_ot()

    def _init_ot(self) -> None:
        """尝试初始化 OTel SDK. 失败 _ot_tracer 保持 None,降级到 buffer."""
        try:
            from opentelemetry import trace  # type: ignore
            from opentelemetry.sdk.resources import Resource  # type: ignore
            from opentelemetry.sdk.trace import TracerProvider  # type: ignore

            resource = Resource.create({"service.name": self._service})
            provider = TracerProvider(resource=resource)
            trace.set_tracer_provider(provider)
            self._ot_tracer = trace.get_tracer(self._service)
            _log.info("OTel tracer initialized: service=%s endpoint=%s", self._service, self._endpoint)
        except Exception as exc:
            _log.warning("OTel SDK init failed, fallback to buffer: %s", exc, exc_info=True)
            self._ot_tracer = None

    @contextmanager
    def span(self, name: str, **attrs: object) -> Iterator[None]:
        """开 span. 异常自动记录 exception event."""
        if self._ot_tracer is not None:
            try:
                with self._ot_tracer.start_as_current_span(name, attributes=dict(attrs)) as sp:
                    try:
                        yield
                    except Exception as exc:
                        try:
                            sp.record_exception(exc)
                        except Exception:
                            pass
                        raise
                return
            except Exception as exc:
                _log.warning("OTel span failed, fallback buffer: %s", exc, exc_info=True)

        # 降级: 本地 buffer
        record = {"name": name, "attrs": dict(attrs), "status": "ok"}
        try:
            yield
        except Exception as exc:
            record["status"] = "error"
            record["error"] = repr(exc)
            with self._lock:
                self._buffer.append(record)
            raise
        with self._lock:
            self._buffer.append(record)

    def metric_inc(self, name: str, value: int = 1, **tags: str) -> None:
        """计数器. OTel 真实 metric 上报超出 MVP 范围,只记日志."""
        _log.debug("metric_inc %s +=%d tags=%s", name, value, tags)

    def metric_observe(self, name: str, value_ms: float, **tags: str) -> None:
        """直方图. MVP 只记日志."""
        _log.debug("metric_observe %s =%.2fms tags=%s", name, value_ms, tags)

    def recent_spans(self, limit: int = 50) -> list[dict[str, Any]]:
        """调试用: 最近 spans (降级 buffer)."""
        with self._lock:
            return list(self._buffer)[-limit:]