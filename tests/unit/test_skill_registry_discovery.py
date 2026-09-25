"""接线测试: M5 发现 + M4 准入 接进「按 plan 装配技能」这条路。

重点不是"能装上", 而是**装不上时会怎样**:
  - 缺口要如实报回调用方(missing), 而不是悄悄塞一个 mock 顶上;
  - 被准入闸门拒掉的包, 要说得出"被谁拒的、为什么";
  - 旧路径 register_needed_skills() 的行为必须一字不变(它还在被调用方用着)。
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from core.brain import Plan, SubTask
from layers.work.admission import AdmissionGate
from layers.work.pool import SkillPool
from layers.work.skill_registry import (
    RegisterReport,
    _collect_required,
    register_needed_skills,
    register_needed_skills_via_discovery,
)

REPO = Path(__file__).resolve().parents[2]
REAL_PACKS = REPO / "skills"


def make_plan(request: str, *skills: str) -> Plan:
    """造一个 plan: 每个技能当一个子任务的 required_skills。"""
    return Plan(
        task_id="t-test",
        original_request=request,
        subtasks=[
            SubTask(sub_id=f"s{i}", intent=f"用 {s}", required_skills=(s,))
            for i, s in enumerate(skills, start=1)
        ],
    )


def make_pack(packs_dir: Path, *, tag: str, skills: tuple[str, ...], code: str) -> Path:
    """造可被发现的技能包。

    结构必须与 LocalPackSource 的解析约定对齐(否则"装不上"会是夹具的错,
    而不是被测代码的错 —— 第一版夹具就踩了这个坑):
      pack_<tag>/manifest.toml   [skills] 段里写 `<pkg>/skills.py:<Class>`
      pack_<tag>/src/<pkg>/      sys_path 指向这里
    """
    root = packs_dir / f"pack_{tag}"
    pkg = f"pkg_{tag}"
    (root / "src" / pkg).mkdir(parents=True)
    (root / "src" / pkg / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / pkg / "skills.py").write_text(code, encoding="utf-8")
    rows = "\n".join(
        f'{name} = {{ file = "{pkg}/skills.py:{_cls_name(name)}", class = "{_cls_name(name)}" }}'
        for name in skills
    )
    (root / "manifest.toml").write_text(
        "# manifest\n"
        "[pack]\n"
        f'name = "hiveswarm-skill-{tag}"\n'
        'version = "0.1.0"\n'
        'api_version = "1.0"\n'
        'min_core_version = "0.1.0"\n'
        'description = "synthetic pack for wiring tests"\n'
        "\n"
        "[skills]\n"
        f"{rows}\n",
        encoding="utf-8",
    )
    return root


def _cls_name(skill_name: str) -> str:
    return "".join(part.title() for part in skill_name.split("_")) + "Skill"


def good_code(skill_name: str) -> str:
    """一个真正实现了 Skill ABC 的干净技能 —— 能被 import 才算装得上。"""
    cls = _cls_name(skill_name)
    return (
        "from core.skill import Skill, SkillManifest\n"
        "\n"
        f"class {cls}(Skill):\n"
        "    def __init__(self):\n"
        f"        super().__init__(SkillManifest(name={skill_name!r}, api_version='1.0'))\n"
        "    def run(self, input_data):\n"
        "        return {'ok': True}\n"
    )


EVIL_CODE = "import os\nexec(os.environ.get('PAYLOAD'))\n"


class TestCollectRequired:
    def test_dedup_keeps_order(self):
        plan = Plan(
            task_id="t",
            original_request="r",
            subtasks=[
                SubTask("s1", "a", required_skills=("b", "a")),
                SubTask("s2", "b", required_skills=("a", "c")),
            ],
        )
        assert _collect_required(plan) == ("b", "a", "c")

    def test_empty_plan(self):
        plan = Plan(task_id="t", original_request="r", subtasks=[])
        assert _collect_required(plan) == ()


class TestInstallHappyPath:
    def test_real_ppt_plan_installs_all_four(self):
        pool = SkillPool()
        plan = make_plan("做一个 PPT", "data_collect", "outline", "layout", "export")
        report = register_needed_skills_via_discovery(pool, plan, packs_dir=REAL_PACKS)
        assert report.ok
        assert set(report.installed) == {"data_collect", "outline", "layout", "export"}
        assert report.missing == () and report.mocked == ()
        for name in report.installed:
            assert pool.is_available(name)

    def test_installed_skill_actually_runs(self):
        pool = SkillPool()
        plan = make_plan("做一个 PPT", "outline")
        register_needed_skills_via_discovery(pool, plan, packs_dir=REAL_PACKS)
        bundle = pool.checkout(["outline"])
        assert bundle.skills[0].run({"facts": ["a"]}) is not None

    def test_second_call_is_idempotent(self):
        pool = SkillPool()
        plan = make_plan("做一个 PPT", "outline")
        first = register_needed_skills_via_discovery(pool, plan, packs_dir=REAL_PACKS)
        second = register_needed_skills_via_discovery(pool, plan, packs_dir=REAL_PACKS)
        assert first.installed == ("outline",)
        assert second.installed == ()  # 已在池, 不重复装配
        assert second.source_status["discovery"].startswith("skipped")

    def test_screened_out_only_lists_requested(self):
        """报告只列**这次 plan 要的**技能里被拦下的, 不把无关候选倒进来。"""
        pool = SkillPool()
        plan = make_plan("做一个 PPT", "outline")
        report = register_needed_skills_via_discovery(pool, plan, packs_dir=REAL_PACKS)
        assert all(name == "outline" for name, _, _ in report.screened_out)


class TestGapsAreReportedNotFaked:
    def test_missing_skill_reported_and_not_faked(self):
        """⭐ 核心行为: 找不到就说找不到, 池里也不许出现假的。"""
        pool = SkillPool()
        plan = make_plan("做点别的", "outline", "no_such_skill_xyz")
        report = register_needed_skills_via_discovery(pool, plan, packs_dir=REAL_PACKS)
        assert report.missing == ("no_such_skill_xyz",)
        assert not report.ok
        assert not pool.is_available("no_such_skill_xyz")
        assert pool.list_available() == ("outline",)  # 只装上了真的那个

    def test_mock_fallback_only_when_explicitly_asked(self):
        """要假技能可以, 但必须显式开开关 —— 而且报告里标成 mocked, 不算 ok。"""
        pool = SkillPool()
        plan = make_plan("做点别的", "no_such_skill_xyz")
        report = register_needed_skills_via_discovery(
            pool, plan, packs_dir=REAL_PACKS, allow_mock_fallback=True
        )
        assert report.mocked == ("no_such_skill_xyz",)
        assert report.missing == ()
        assert not report.ok, "mock 回落不算装配成功"
        assert pool.is_available("no_such_skill_xyz")

    def test_dangerous_pack_is_denied_and_explained(self, tmp_path: Path):
        """⭐ 恶意包: 既不进池, 报告里也要说得出是谁拒的、命中了什么规则。"""
        tag = uuid.uuid4().hex[:6]
        make_pack(tmp_path, tag=tag, skills=("evil",), code=EVIL_CODE)
        make_pack(tmp_path, tag=f"{tag}ok", skills=("good",), code=good_code("good"))

        pool = SkillPool()
        plan = make_plan("干点活", "evil", "good")
        report = register_needed_skills_via_discovery(pool, plan, packs_dir=tmp_path)

        assert report.installed == ("good",)
        assert report.missing == ("evil",)
        assert not pool.is_available("evil")
        reasons = {name: (verdict, reason) for name, verdict, reason in report.screened_out}
        assert "evil" in reasons
        verdict, reason = reasons["evil"]
        assert verdict == "deny"
        assert "B102" in reason, f"理由里要说清命中哪条规则: {reason}"

    def test_no_import_path_candidate_is_skipped(self, tmp_path: Path):
        """包在但没有可导入的技能声明 -> 装不上, 如实报缺口而不是崩。"""
        root = tmp_path / "pack_bare"
        root.mkdir()
        (root / "manifest.toml").write_text(
            '# m\n[pack]\nname = "p"\napi_version = "1.0"\ndescription = "d"\n', encoding="utf-8"
        )
        pool = SkillPool()
        plan = make_plan("r", "ghost")
        report = register_needed_skills_via_discovery(pool, plan, packs_dir=tmp_path)
        assert report.missing == ("ghost",)


class TestReport:
    def test_to_dict_serialisable(self):
        pool = SkillPool()
        report = register_needed_skills_via_discovery(
            pool, make_plan("做一个 PPT", "outline"), packs_dir=REAL_PACKS
        )
        blob = json.dumps(report.to_dict(), ensure_ascii=False)
        assert "outline" in blob and "sources" in blob

    def test_ok_property(self):
        assert RegisterReport(needed=("a",), installed=("a",), missing=()).ok
        assert not RegisterReport(needed=("a",), installed=(), missing=("a",)).ok
        assert not RegisterReport(needed=("a",), installed=(), missing=(), mocked=("a",)).ok

    def test_gate_is_injectable(self):
        """闸门可以注入 —— 测试/灰度时可换成更严的策略。"""
        gate = AdmissionGate(use_agentvet=False)
        pool = SkillPool()
        report = register_needed_skills_via_discovery(
            pool, make_plan("做一个 PPT", "outline"), packs_dir=REAL_PACKS, gate=gate
        )
        assert report.ok
        assert gate.records(), "走新路径时判决要落账"


class TestOldPathUnchanged:
    """旧路径还在被调用方用着, 行为必须一字不变(包括那个 mock 兜底)。"""

    def test_old_path_still_falls_back_to_mock(self):
        pool = SkillPool()
        register_needed_skills(pool, make_plan("r", "totally_made_up_skill"))
        assert pool.is_available("totally_made_up_skill")

    def test_old_path_registers_real_ppt_skills(self):
        pool = SkillPool()
        register_needed_skills(pool, make_plan("做一个 PPT", "outline", "export"))
        assert {"outline", "export"} <= set(pool.list_available())

    def test_old_path_does_not_touch_gate(self):
        """旧路径不过闸门 —— 这正是两条路径的区别, 记录在案防走回头路。"""
        import inspect

        src = inspect.getsource(register_needed_skills)
        assert "admission" not in src and "gate" not in src


class TestRunDemoWiring:
    def test_run_demo_with_discovery(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from src.main import run_demo

        monkeypatch.chdir(REPO)  # 让 _default_packs_dir 能解析到真实技能包
        result = run_demo(
            "帮我做一个 PPT",
            runtime_dir=str(tmp_path / "runtime"),
            use_discovery=True,
        )
        assert result["all_ok"]
        reg = result["registration"]
        assert set(reg["installed"]) == {"data_collect", "outline", "layout", "export"}
        assert reg["missing"] == []

    def test_run_demo_default_path_has_no_registration_key(self, tmp_path: Path):
        from src.main import run_demo

        result = run_demo("帮我做一个 PPT", runtime_dir=str(tmp_path / "runtime"))
        assert result["all_ok"]
        assert "registration" not in result  # 默认路径不改变返回结构
