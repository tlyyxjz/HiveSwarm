"""Tests for stub.audit_kafka.KafkaAudit.

Mock confluent_kafka.Producer, 验 JSONL 序列化 / 异常降级 / flush.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from stub.audit_kafka import KafkaAudit


def test_stub_implements_abc():
    from core.audit import AuditLogger

    assert set(AuditLogger.__abstractmethods__) <= set(dir(KafkaAudit))


def test_log_writes_jsonl_when_producer_none(tmp_path):
    """confluent_kafka 未装 → log 降级写本地 JSONL."""
    audit = KafkaAudit(
        brokers=["localhost:9092"],
        topic="test.audit",
        fallback_path=tmp_path / "audit.jsonl",
    )
    # 强制模拟 producer 不可用
    audit._producer = None

    audit.log(actor="alice", action="skill.run", target="crawler", result="ok", metadata={"tokens": 100})
    audit.log(actor="bob", action="skill.fail", target="ppt", result="error", metadata={"err": "oom"})

    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    import json
    rec0 = json.loads(lines[0])
    assert rec0["actor"] == "alice"
    assert rec0["action"] == "skill.run"
    assert rec0["metadata"]["tokens"] == 100
    assert "ts" in rec0


def test_log_uses_producer_when_available(tmp_path):
    """Producer 可用 → log 调 produce + poll,不写 fallback."""
    audit = KafkaAudit(brokers=["localhost:9092"], topic="t", fallback_path=tmp_path / "fb.jsonl")
    mock_producer = MagicMock()
    audit._producer = mock_producer

    audit.log(actor="alice", action="skill.run")
    mock_producer.produce.assert_called_once()
    mock_producer.poll.assert_called_once_with(0)

    # callback fallback 路径不走
    assert not (tmp_path / "fb.jsonl").exists()


def test_query_reads_fallback_with_filter(tmp_path):
    """query 读 fallback JSONL,actor/action 过滤."""
    audit = KafkaAudit(brokers=["x"], topic="t", fallback_path=tmp_path / "q.jsonl")
    audit._producer = None

    audit.log(actor="alice", action="skill.run")
    audit.log(actor="bob", action="skill.run")
    audit.log(actor="alice", action="skill.fail")

    only_alice = audit.query(actor="alice")
    assert len(only_alice) == 2
    assert all(r["actor"] == "alice" for r in only_alice)

    only_alice_run = audit.query(actor="alice", action="skill.run")
    assert len(only_alice_run) == 1

    empty = audit.query(actor="nobody")
    assert empty == []