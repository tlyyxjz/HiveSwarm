"""config_loader 单元测试."""
from __future__ import annotations

from pathlib import Path

import pytest

from stub.config_loader import ConfigError, load_config


def test_load_default_only():
    cfg = load_config()
    assert cfg.brain.llm_model == "qwen3:8b"
    assert cfg.repair.strategy == "switch_first"


def test_load_mvp_override():
    cfg = load_config(override_path="config/mvp.toml")
    assert cfg.monitor.dashboard_port == 7861  # mvp override
    assert cfg.brain.llm_model == "qwen3:8b"  # 来自 default
    assert "config/default.toml" in cfg.source_files
    assert "config/mvp.toml" in cfg.source_files


def test_missing_file_raises():
    with pytest.raises(ConfigError, match="config not found"):
        load_config(override_path="nope.toml")


def test_config_is_frozen():
    cfg = load_config()
    with pytest.raises(Exception):  # FrozenInstanceError
        cfg.brain = cfg.brain  # type: ignore[misc]


def test_skills_enabled_parsed_as_tuple(tmp_path: Path):
    custom = tmp_path / "c.toml"
    custom.write_text(
        '[skills]\nenabled = ["a", "b"]\n', encoding="utf-8"
    )
    cfg = load_config(override_path=custom)
    assert cfg.skills.enabled == ("a", "b")
