"""src.main 集成测试."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.main import run_demo


class TestRunDemo:
    def test_ppt_request_runs_to_completion(self, tmp_path, capsys):
        result = run_demo("帮我做一个 PPT", runtime_dir=str(tmp_path / "rt"))
        assert result["all_ok"] is True
        assert result["success_count"] == 4
        assert result["fail_count"] == 0
        # 4 个 subtask
        assert len(result["subtasks"]) == 4
        # task_id 有
        assert result["task_id"]

    def test_scan_request_uses_mock_not_real_scanner(self, tmp_path):
        """scan 请求不应调用真 agentvet 扫描器(太慢), 验证走 mock EchoSkill."""
        with patch("layers.work.skill_registry._try_register_real_skill", return_value=False):
            result = run_demo("扫描这个项目", runtime_dir=str(tmp_path / "rt"))
        # mock EchoSkill 全部 ok
        assert result["all_ok"] is True
        assert result["success_count"] >= 2

    def test_unknown_request_still_runs(self, tmp_path):
        result = run_demo("hello world", runtime_dir=str(tmp_path / "rt"))
        # mock 默认 1 个 subtask 但无 required_skills, 会跑但可能 fail
        # 验证: 至少 0 成功 + fail_count 等于 subtask 数
        assert result["success_count"] + result["fail_count"] >= 1

    def test_results_have_required_fields(self, tmp_path):
        result = run_demo("帮我做一个 PPT", runtime_dir=str(tmp_path / "rt"))
        for r in result["results"]:
            assert "sub_id" in r
            assert "ok" in r
            assert "result" in r

    def test_runtime_dir_created(self, tmp_path):
        run_demo("x", runtime_dir=str(tmp_path / "rt"))
        assert (tmp_path / "rt").exists()


def test_main_prints_text(capsys):
    """main() 跑一次, 输出含 'Task ID'."""
    from src.main import main

    rc = main(["帮我做一个 PPT", "--runtime", "/tmp/hs_test_main"])
    out = capsys.readouterr().out
    assert "Task ID" in out
    assert rc == 0
