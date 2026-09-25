"""M5 技能发现单元测试.

覆盖分层:
  源层    —— 本地包 / 池 / entry_point / GitHub(用 MockTransport, 不出网)
  打分层  —— 可解释 breakdown; 名字命中是硬信号
  筛查层  —— 候选 -> 过闸门; 远程候选 fail-closed
  装配层  —— 唯一入口; 装配前重判(TOCTOU); 真装真跑
对抗性  —— 静态检查"有没有绕过闸门的注册路径"
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

import httpx
import pytest

from core.events import EventType
from core.skill import Skill, SkillManifest
from layers.work.admission import AdmissionGate, TrustLevel, Verdict
from layers.work.discovery import (
    DiscoveryResult,
    EntryPointSource,
    GitHubRepoSource,
    LocalPackSource,
    PoolSource,
    ScoredCandidate,
    SearchQuery,
    SkillCandidate,
    SkillDiscovery,
    _parse_frontmatter,
    _parse_pack_skills,
    _tokens,
    build_default_discovery,
    score_candidate,
)
from layers.work.pool import SkillPool
from stub.bus_local import LocalEventBus

REPO = Path(__file__).resolve().parents[2]
REAL_PACKS = REPO / "skills"


class _FakeSkill(Skill):
    def __init__(self, name: str = "demo") -> None:
        super().__init__(SkillManifest(name=name, api_version="1.0"))

    def run(self, input_data: dict) -> dict:
        return {"ok": True, "echo": input_data}


def make_importable_pack(tmp_path: Path, *, clean: bool = True) -> Path:
    """造一个真能 import 的技能包(名字带随机后缀, 避免 sys.modules 互撞)。"""
    tag = uuid.uuid4().hex[:6]
    pkg = f"hsp{tag}"
    root = tmp_path / f"pack_{tag}"
    (root / "src" / pkg).mkdir(parents=True)
    (root / "manifest.toml").write_text(
        "# manifest\n"
        "[pack]\n"
        f'name = "hiveswarm-skill-{tag}"\n'
        'version = "0.1.0"\n'
        'api_version = "1.0"\n'
        'min_core_version = "0.1.0"\n'
        'description = "synthetic test pack"\n'
        "\n"
        "[skills]\n"
        f'demo = {{ file = "{pkg}/skills.py:DemoSkill", class = "DemoSkill" }}\n',
        encoding="utf-8",
    )
    (root / "src" / pkg / "__init__.py").write_text("", encoding="utf-8")
    body = (
        "from core.skill import Skill, SkillManifest\n"
        "\n"
        "class DemoSkill(Skill):\n"
        "    def __init__(self):\n"
        "        super().__init__(SkillManifest(name='demo', api_version='1.0'))\n"
        "    def run(self, input_data):\n"
        "        return {'ok': True, 'echo': input_data}\n"
    )
    (root / "src" / pkg / "skills.py").write_text(body, encoding="utf-8")
    return root


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# ── 解析辅助 ──────────────────────────────────────────────────────────────


class TestParsers:
    def test_frontmatter_flat_scalars(self):
        text = "---\nname: my-skill\ndescription: does things\nlicense: MIT\n---\n\n# body\n"
        fm = _parse_frontmatter(text)
        assert fm["name"] == "my-skill"
        assert fm["description"] == "does things"

    def test_frontmatter_missing_returns_empty(self):
        assert _parse_frontmatter("# no frontmatter\n") == {}

    def test_frontmatter_ignores_comments_and_blank(self):
        text = "---\n# note\n\nname: x\n---\n"
        assert _parse_frontmatter(text) == {"name": "x"}

    def test_pack_skills_extracts_module_and_class(self):
        text = (
            "# c\n[pack]\nname = \"p\"\n\n[skills]\n"
            'a = { file = "pkg/skills.py:ASkill", class = "ASkill" }\n'
            'b = { file = "pkg/sub/x.py:BSkill", class = "BSkill" }\n'
        )
        assert _parse_pack_skills(text) == {
            "a": "pkg.skills:ASkill",
            "b": "pkg.sub.x:BSkill",
        }

    def test_pack_skills_ignores_other_sections(self):
        text = '[pack]\nname = "p"\n'
        assert _parse_pack_skills(text) == {}

    def test_tokens_handles_chinese_and_english(self):
        tok = _tokens("做PPT 演示 outline")
        assert "ppt" in tok and "演示" in tok and "outline" in tok


# ── 源层 ──────────────────────────────────────────────────────────────────


class TestLocalPackSource:
    def test_finds_real_repo_packs(self):
        src = LocalPackSource(REAL_PACKS)
        found = src.search(SearchQuery(intent="ppt"))
        names = {c.name for c in found}
        assert {"outline", "layout", "export", "http_fetch", "web_search"} <= names
        assert all(c.trust is TrustLevel.FIRST_PARTY for c in found)

    def test_candidate_carries_import_path_and_syspath(self):
        src = LocalPackSource(REAL_PACKS)
        outline = next(c for c in src.search(SearchQuery()) if c.name == "outline")
        assert outline.import_path == "ppt_pack.skills:OutlineSkill"
        assert outline.sys_path.endswith("ppt_pack") or "ppt_pack" in outline.sys_path
        assert outline.root is not None and not outline.needs_fetch

    def test_missing_dir_reports_error_not_raises(self, tmp_path: Path):
        src = LocalPackSource(tmp_path / "nope")
        assert src.search(SearchQuery()) == []
        assert "not found" in src.last_error

    def test_skill_md_frontmatter_also_discovered(self, tmp_path: Path):
        pack = tmp_path / "md_pack"
        pack.mkdir()
        (pack / "manifest.toml").write_text(
            '# c\n[pack]\nname = "p"\napi_version = "1.0"\ndescription = "d"\n', encoding="utf-8"
        )
        (pack / "SKILL.md").write_text(
            "---\nname: patch-notes\ndescription: writes release notes\n---\n", encoding="utf-8"
        )
        found = LocalPackSource(tmp_path).search(SearchQuery())
        assert any(c.name == "patch-notes" for c in found)


class TestPoolSource:
    def test_lists_registered_skills(self):
        pool = SkillPool()
        pool.register(_FakeSkill("alpha"))
        out = PoolSource(pool).search(SearchQuery())
        assert [c.name for c in out] == ["alpha"]
        assert out[0].kind == "pool"

    def test_empty_pool(self):
        assert PoolSource(SkillPool()).search(SearchQuery()) == []


class TestEntryPointSource:
    def test_no_entry_points_is_empty_not_error(self):
        src = EntryPointSource(group="hiveswarm.does.not.exist")
        assert src.search(SearchQuery()) == []


class TestGitHubRepoSource:
    PAYLOAD = {
        "items": [
            {
                "full_name": "acme/skill-x",
                "description": "does x",
                "html_url": "https://github.com/acme/skill-x",
                "topics": ["claude-skill", "python"],
                "stargazers_count": 42,
            },
            {"full_name": ""},
        ]
    }

    def test_parses_items_and_marks_unverified(self):
        src = GitHubRepoSource(client=mock_client(lambda r: httpx.Response(200, json=self.PAYLOAD)))
        out = src.search(SearchQuery(intent="x"))
        assert len(out) == 1  # 空 full_name 的条目被丢掉
        c = out[0]
        assert c.name == "skill-x"
        assert c.kind == "github_repo"
        assert c.trust is TrustLevel.UNVERIFIED
        assert c.needs_fetch and c.root is None
        assert c.remote_url == "https://github.com/acme/skill-x"
        assert c.stars == 42

    def test_query_uses_official_topics_and_language(self):
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["q"] = request.url.params.get("q", "")
            seen["sort"] = request.url.params.get("sort", "")
            return httpx.Response(200, json={"items": []})

        GitHubRepoSource(client=mock_client(handler), topic="claude-skill").search(
            SearchQuery(intent="x", tags=("agent-skill",), required_skills=("outline",))
        )
        assert "topic:claude-skill" in seen["q"]
        assert "topic:agent-skill" in seen["q"]
        assert "outline" in seen["q"] and "language:Python" in seen["q"]
        assert seen["sort"] == "stars"

    def test_http_error_degrades_to_empty(self):
        src = GitHubRepoSource(client=mock_client(lambda r: httpx.Response(403, text="rate limited")))
        assert src.search(SearchQuery()) == []
        assert "403" in src.last_error

    def test_network_exception_degrades_to_empty(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        src = GitHubRepoSource(client=mock_client(handler))
        assert src.search(SearchQuery()) == []  # 不抛
        assert "ConnectError" in src.last_error

    def test_disabled_source_returns_empty_with_reason(self):
        src = GitHubRepoSource(enabled=False)
        assert src.search(SearchQuery()) == []
        assert src.last_error == "disabled by config"

    def test_token_becomes_bearer_header(self):
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("authorization", "")
            return httpx.Response(200, json={"items": []})

        GitHubRepoSource(client=mock_client(handler), token="t0k").search(SearchQuery())
        assert captured["auth"] == "Bearer t0k"


# ── 打分 ──────────────────────────────────────────────────────────────────


class TestScoring:
    def _cand(self, name: str, desc: str = "", tags: tuple[str, ...] = ()) -> SkillCandidate:
        return SkillCandidate(
            name=name, kind="local_pack", source="t", description=desc, tags=tags,
            trust=TrustLevel.FIRST_PARTY,
        )

    def test_required_skill_hit_dominates(self):
        q = SearchQuery(intent="anything", required_skills=("outline",))
        hit = score_candidate(self._cand("outline", "unrelated words"), q)
        miss = score_candidate(self._cand("totally_other", "outline outline outline"), q)
        assert hit.score >= 0.9 > miss.score

    def test_breakdown_has_all_components(self):
        s = score_candidate(self._cand("a", "b"), SearchQuery(intent="b"))
        assert set(s.breakdown) == {"name", "tag", "text", "trust", "health"}

    def test_tag_overlap_is_ratio(self):
        q = SearchQuery(tags=("ppt", "export"))
        s = score_candidate(self._cand("x", tags=("ppt",)), q)
        assert s.breakdown["tag"] == pytest.approx(0.5)

    def test_text_overlap_uses_intent(self):
        q = SearchQuery(intent="生成幻灯片")
        hi = score_candidate(self._cand("x", "生成幻灯片工具"), q)
        lo = score_candidate(self._cand("y", "network scanner"), q)
        assert hi.breakdown["text"] > lo.breakdown["text"] == 0.0

    def test_health_is_clamped(self):
        s = score_candidate(self._cand("a"), SearchQuery(), health=5.0)
        assert s.breakdown["health"] == 1.0

    def test_low_trust_scores_lower(self):
        q = SearchQuery()
        hi = score_candidate(self._cand("a"), q)
        lo = score_candidate(
            SkillCandidate("a", "github_repo", "t", trust=TrustLevel.UNVERIFIED), q
        )
        assert hi.score > lo.score

    def test_scored_candidate_exposes_name(self):
        s: ScoredCandidate = score_candidate(self._cand("zzz"), SearchQuery())
        assert s.name == "zzz"


# ── 筛查 / 发现 ───────────────────────────────────────────────────────────


class TestScreen:
    def _disc(self, tmp_path: Path, pool: SkillPool | None = None) -> SkillDiscovery:
        return SkillDiscovery(
            [LocalPackSource(tmp_path)], AdmissionGate(use_agentvet=False), pool=pool
        )

    def test_remote_candidate_is_quarantined(self, tmp_path: Path):
        out = self._disc(tmp_path).screen(
            SkillCandidate("remote-x", "github_repo", "github", remote_url="u")
        )
        assert out.verdict is Verdict.QUARANTINE
        assert "fail-closed" in out.reason
        assert not out.selected

    def test_pool_candidate_passes_without_rescan(self, tmp_path: Path):
        out = self._disc(tmp_path).screen(SkillCandidate("a", "pool", "pool"))
        assert out.verdict is Verdict.ALLOW and out.selected

    def test_local_clean_pack_is_allow(self, tmp_path: Path):
        root = make_importable_pack(tmp_path)
        cand = LocalPackSource(root.parent).search(SearchQuery(intent="demo"))[0]
        assert self._disc(tmp_path).screen(cand).selected

    def test_local_dangerous_pack_is_denied(self, tmp_path: Path):
        root = make_importable_pack(tmp_path)
        next((root / "src").glob("*/skills.py")).write_text("exec('boom')\n", encoding="utf-8")
        cand = LocalPackSource(root.parent).search(SearchQuery(intent="demo"))[0]
        out = self._disc(tmp_path).screen(cand)
        assert out.verdict is Verdict.DENY
        assert "B102" in out.rule_ids

    def test_same_pack_screened_once(self, tmp_path: Path):
        """一个包出 N 个技能时, 包级判决复用 —— 否则同一个包被扫 N 遍。"""
        root = tmp_path / "multi"
        (root / "src").mkdir(parents=True)
        (root / "manifest.toml").write_text(
            "# c\n[pack]\nname = \"p\"\napi_version = \"1.0\"\ndescription = \"d\"\n\n[skills]\n"
            'a = { file = "x.py:A", class = "A" }\n'
            'b = { file = "x.py:B", class = "B" }\n'
            'c = { file = "x.py:C", class = "C" }\n',
            encoding="utf-8",
        )
        (root / "skills.py").write_text("x = 1\n", encoding="utf-8")
        gate = AdmissionGate(use_agentvet=False)
        disc = SkillDiscovery([LocalPackSource(tmp_path)], gate)
        disc.discover("x")
        assert len(gate.records()) == 1, "同包应只审一次"


class TestDiscover:
    def test_end_to_end_on_real_packs(self):
        pool = SkillPool()
        disc = build_default_discovery(packs_dir=REAL_PACKS, pool=pool)
        res = disc.discover("做一个PPT演示", required_skills=("outline", "layout", "export"))
        assert isinstance(res, DiscoveryResult)
        assert len(res.candidates) >= 10
        assert {s.name for s in res.chosen} >= {"outline", "layout", "export"}
        assert res.source_status["local_pack"].startswith("ok")
        conn = res.candidates[0].candidate
        assert conn.kind in {"local_pack", "pool", "entry_point"}

    def test_chosen_is_not_truncated(self):
        """chosen 是"允许装配的全集", 不能因为 top_k 就少列 —— 少列就成了说不清的状态。"""
        disc = build_default_discovery(packs_dir=REAL_PACKS)
        res = disc.discover("ppt")
        assert len(res.chosen) > 3

    def test_result_summary_is_readable(self):
        disc = build_default_discovery(packs_dir=REAL_PACKS)
        assert "candidates=" in disc.discover("ppt").summary()

    def test_source_failure_does_not_kill_discovery(self):
        class _Broken:
            name = "broken"

            def search(self, query):
                raise RuntimeError("source down")

            @property
            def last_error(self) -> str:
                return ""

        disc = SkillDiscovery([_Broken(), LocalPackSource(REAL_PACKS)], AdmissionGate(use_agentvet=False))
        res = disc.discover("ppt")
        assert res.candidates, "一个源挂了, 其余源的结果仍要出来"
        assert "error" in res.source_status["broken"]

    def test_dedup_keeps_higher_trust(self, tmp_path: Path):
        root = make_importable_pack(tmp_path)
        pool = SkillPool()
        disc = SkillDiscovery([LocalPackSource(root.parent), PoolSource(pool)], AdmissionGate(use_agentvet=False))
        res = disc.discover("demo")
        names = [s.name for s in res.candidates]
        assert names.count("demo") == 1

    def test_no_sources_is_rejected_at_construction(self):
        with pytest.raises(ValueError):
            SkillDiscovery([], AdmissionGate())


# ── 装配 ──────────────────────────────────────────────────────────────────


class TestInstallSelected:
    def test_registers_real_skills_that_run(self):
        pool = SkillPool()
        disc = build_default_discovery(packs_dir=REAL_PACKS, pool=pool)
        res = disc.discover("做一个PPT演示", required_skills=("outline", "layout", "export"))
        installed = disc.install_selected(res, top_k=2)
        assert len(installed) == 2
        assert all(pool.is_available(n) for n in installed)
        bundle = pool.checkout([installed[0]])
        assert bundle.skills[0].run({}) is not None

    def test_requires_pool(self):
        disc = build_default_discovery(packs_dir=REAL_PACKS)
        res = disc.discover("ppt")
        with pytest.raises(ValueError):
            disc.install_selected(res)

    def test_skips_remote_candidates(self, tmp_path: Path):
        pool = SkillPool()
        disc = SkillDiscovery([LocalPackSource(tmp_path)], AdmissionGate(use_agentvet=False), pool=pool)
        res = DiscoveryResult(
            intent="x",
            chosen=(
                ScoredCandidate(
                    SkillCandidate("remote", "github_repo", "github", remote_url="u"), 0.5
                ),
            ),
        )
        assert disc.install_selected(res) == ()
        assert pool.list_available() == ()

    def test_rechecks_at_install_time(self, tmp_path: Path):
        """TOCTOU: 发现与装配之间内容可能被换掉, 所以装配前必须重判。"""
        root = make_importable_pack(tmp_path)
        pool = SkillPool()
        disc = SkillDiscovery(
            [LocalPackSource(root.parent)], AdmissionGate(use_agentvet=False), pool=pool
        )
        res = disc.discover("demo", ("demo",))
        assert [s.name for s in res.chosen] == ["demo"]

        # 装配之前把包内容换成恶意的 —— 不能拿着筛查时的旧结论放行
        next((root / "src").glob("*/skills.py")).write_text("exec('boom')\n", encoding="utf-8")
        assert disc.install_selected(res) == ()
        assert pool.list_available() == ()

    def test_installed_skill_appears_via_pool_source(self, tmp_path: Path):
        root = make_importable_pack(tmp_path)
        pool = SkillPool()
        gate = AdmissionGate(use_agentvet=False)
        disc = SkillDiscovery([LocalPackSource(root.parent)], gate, pool=pool)
        disc.install_selected(disc.discover("demo", ("demo",)))
        assert "demo" in pool.list_available()
        assert "demo" in {c.name for c in PoolSource(pool).search(SearchQuery())}


# ── 对抗性: 唯一入口 ──────────────────────────────────────────────────────


class TestNoBypass:
    """静态防线: 产品代码里直接注册技能的位置必须收敛。

    这不是语言级强制(Python 没有 friend), 但它把"绕过闸门"变成 CI 里**立刻可见**
    的一件事: 新增一处绕过, 测试就红. 白名单里两项各自的理由写在注释里.
    """
    ALLOWLIST = {
        "layers/work/admission.py",  # 唯一入口 register_if_admitted
        "layers/work/skill_registry.py",  # 旧路径, 尚未接入闸门(见 T1.6 非目标)
    }

    def test_pool_register_only_from_allowlisted_modules(self):
        offenders: list[str] = []
        pattern = re.compile(r"\.register\s*\(")
        for base in ("core", "layers", "gateway", "src", "sdk", "stub"):
            for py in (REPO / base).rglob("*.py"):
                rel = py.relative_to(REPO).as_posix()
                if rel in self.ALLOWLIST:
                    continue
                if pattern.search(py.read_text(encoding="utf-8", errors="replace")):
                    offenders.append(rel)
        assert not offenders, f"检测到绕过准入闸门的注册调用: {offenders}"

    def test_allowlist_entries_still_exist(self):
        """白名单不能变成幽灵条目: 文件没了就该删规则。"""
        for rel in self.ALLOWLIST:
            assert (REPO / rel).is_file(), f"白名单里的 {rel} 已不存在, 请更新该测试"


# ── 事件 ──────────────────────────────────────────────────────────────────


class TestEvents:
    def test_discovered_and_screened_events(self):
        bus = LocalEventBus()
        seen: dict[str, list[dict]] = {"d": [], "s": []}
        bus.subscribe(EventType.SKILL_DISCOVERED, lambda e: seen["d"].append(e.payload))
        bus.subscribe(EventType.SKILL_SCREENED, lambda e: seen["s"].append(e.payload))
        disc = build_default_discovery(packs_dir=REAL_PACKS, bus=bus)
        disc.discover("ppt", ("outline",))
        assert seen["d"] and seen["d"][0]["source"] == "local_pack"
        assert seen["s"] and "outline" in seen["s"][0]["chosen"]

    def test_bus_failure_does_not_break_discovery(self):
        class _BadBus(LocalEventBus):
            def publish(self, event):  # type: ignore[override]
                raise RuntimeError("bus down")

        disc = build_default_discovery(packs_dir=REAL_PACKS, bus=_BadBus())
        assert disc.discover("ppt").candidates
