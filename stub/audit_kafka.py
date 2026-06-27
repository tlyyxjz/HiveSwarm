"""KafkaAudit stub — confluent_kafka.Producer 软依赖.

生产替换: stub.audit_logfile.LogFileAudit → stub.audit_kafka.KafkaAudit.
        失败降级到本地文件 (LogFileAudit 复用),不阻塞业务.

依赖: confluent-kafka (TYPE_CHECKING 软依赖).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.audit import AuditLogger

if TYPE_CHECKING:
    from confluent_kafka import Producer

_log = logging.getLogger(__name__)


class KafkaAudit(AuditLogger):
    """审计写入 Kafka. 不可达时降级到本地 JSONL.

    Args:
        brokers: Kafka broker 列表 ["host:9092", ...]
        topic: 目标 topic
        fallback_path: 降级 JSONL 文件路径
    """

    def __init__(
        self,
        brokers: list[str],
        topic: str = "hiveswarm.audit",
        fallback_path: str | Path = "logs/audit_kafka_fallback.jsonl",
    ) -> None:
        self._brokers = brokers
        self._topic = topic
        self._fallback = Path(fallback_path).expanduser()
        self._fallback.parent.mkdir(parents=True, exist_ok=True)
        self._producer: Any = None  # confluent_kafka.Producer | None
        self._connect()

    def _connect(self) -> None:
        """尝试连接. 失败 _producer 保持 None,后续降级."""
        try:
            from confluent_kafka import Producer  # type: ignore

            self._producer = Producer({"bootstrap.servers": ",".join(self._brokers)})
            _log.info("Kafka producer connected: %s", self._brokers)
        except Exception as exc:
            _log.warning("Kafka connect failed, fallback to file: %s", exc, exc_info=True)
            self._producer = None

    def _fallback_log(self, record: dict[str, Any]) -> None:
        try:
            with self._fallback.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            _log.warning("fallback audit write failed: %s", exc, exc_info=True)

    def log(
        self,
        actor: str,
        action: str,
        target: str = "",
        result: str = "ok",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        record = {
            "ts": datetime.now().isoformat(),
            "actor": actor,
            "action": action,
            "target": target,
            "result": result,
            "metadata": metadata or {},
        }
        if self._producer is None:
            self._fallback_log(record)
            return
        try:
            payload = json.dumps(record, ensure_ascii=False).encode("utf-8")

            def _on_delivery(err: Any, _msg: Any) -> None:
                if err is not None:
                    _log.warning("kafka delivery failed: %s", err, exc_info=True)
                    self._fallback_log(record)

            self._producer.produce(self._topic, value=payload, on_delivery=_on_delivery)
            self._producer.poll(0)  # 非阻塞触发回调
        except Exception as exc:
            _log.warning("kafka produce failed, fallback: %s", exc, exc_info=True)
            self._fallback_log(record)

    def query(
        self,
        actor: str | None = None,
        action: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Kafka 不可查询,降级读 fallback 文件."""
        if not self._fallback.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self._fallback.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if actor and rec.get("actor") != actor:
                continue
            if action and rec.get("action") != action:
                continue
            if since and datetime.fromisoformat(rec["ts"]) < since:
                continue
            out.append(rec)
            if len(out) >= limit:
                break
        return out

    def flush(self, timeout_s: float = 5.0) -> None:
        """阻塞 flush,退出前调用."""
        if self._producer is not None:
            try:
                self._producer.flush(timeout_s)
            except Exception as exc:
                _log.warning("kafka flush failed: %s", exc, exc_info=True)

    def close(self) -> None:
        self.flush()