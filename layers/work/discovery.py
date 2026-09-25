"""SkillDiscovery — 运行时技能发现: 候选区 → 筛查 → 装配 (M5).

跟"所有技能常驻内存"的做法不同, 本层的流程是:

    intent / required_skills
        ↓  (多源检索)
    candidates        候选区 —— 只是"可能有用", 什么都还没验
        ↓  (打分排序, 可解释)
    ranked
        ↓  (过 AdmissionGate, M4)
    chosen            通过准入, 允许装配
    screened_out      没过 / 暂不可判, 附理由, 不进池
        ↓  (register_if_admitted, 唯一入口)
    in pool

三个设计约束:
  1. **候选 != 可信**. 候选区里的东西什么都不是 —— 它只是"检索命中了".
     任何试图从 candidates 直接拿东西去跑的代码都是 bug.
  2. **打分必须可解释**. 每个候选带 score_breakdown, 追问"为什么选它"能逐项答.
  3. **远程候选不能自动装配**. GitHub 搜到的仓库是**未取回本地的 URL**,
     没有内容可扫 -> 按 fail-closed 记 QUARANTINE. 自动下载并注册第三方代码
     等于把闸门开在取回之前, 本层不做.

复用 vs 自造(按"能用现成的先用"):
  - GitHub 检索: 用官方 REST Search API, 不自己爬页面.
  - 第三方技能发现: 用 Python 标准 entry_points 机制(pyproject.toml 里
    `[project.entry-points."hiveswarm.skills"]` 已经预留), 不自己发明插件协议.
  - SKILL.md frontmatter: 解析事实标准字段(name/description), 兼容第三方技能包.
  - 打分/筛查/装配这三段是自造的 —— 市面上没现成的, 因为它是本框架特有的
    "借还"语义的一部分.

依赖方向: discovery -> admission / core.skill (单向), 不反向.
"""
from __future__ import annotations

import importlib
import logging
import re
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.skill import Skill
from layers.work.admission import (
    AdmissionGate,
    AdmissionSubject,
    TrustLevel,
    Verdict,
)

if TYPE_CHECKING:
    from core.events import EventBus
    from layers.work.pool import SkillPool

_log = logging.getLogger(__name__)

# 各打分项的权重。和 = 1.0, 便于读分数时直接当百分比。
_DEFAULT_WEIGHTS: dict[str, float] = {
    "name": 0.45,  # 显式声明的技能名命中 —— 最强信号
    "tag": 0.20,  # 标签重叠
    "text": 0.20,  # 意图文本与描述的相似度
    "trust": 0.10,  # 来源可信度
    "health": 0.05,  # 已在池中的历史健康度
}

_SOURCE_WEIGHT: dict[TrustLevel, float] = {
    TrustLevel.FIRST_PARTY: 1.0,
    TrustLevel.SIGNED: 0.7,
    TrustLevel.UNVERIFIED: 0.3,
}


# ── 数据类型 ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SearchQuery:
    """一次检索的输入。required_skills 来自 Plan 的 subtask, 是最硬的信号。"""

    intent: str = ""
    required_skills: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillCandidate:
    """候选区里的一条。注意: 有这条数据 **不代表任何可信性**。"""

    name: str
    kind: str  # local_pack | pool | entry_point | github_repo
    source: str  # 哪个 source 给出的
    description: str = ""
    tags: tuple[str, ...] = ()
    trust: TrustLevel = TrustLevel.UNVERIFIED
    root: Path | None = None  # 本地包根目录(没有 = 无可扫描内容)
    import_path: str = ""  # "module:Class", 装配时用
    sys_path: str = ""  # 需要注入的 sys.path 提示
    remote_url: str = ""
    stars: int = 0

    @property
    def needs_fetch(self) -> bool:
        """远程候选: 内容不在本地, 无法准入。"""
        return self.root is None


@dataclass
class ScoredCandidate:
    """候选 + 打分。breakdown 逐项可查, 不接受"综合评分很高"这种说法。"""

    candidate: SkillCandidate
    score: float
    breakdown: dict[str, float] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.candidate.name


@dataclass(frozen=True)
class ScreeningOutcome:
    """筛查结论。没过也要带理由 —— 否则"为什么没选它"就成了不可回答的问题。"""

    name: str
    verdict: Verdict
    reason: str
    rule_ids: tuple[str, ...] = ()

    @property
    def selected(self) -> bool:
        return self.verdict is Verdict.ALLOW


@dataclass
class DiscoveryResult:
    """一次发现的完整结果。"""

    intent: str
    required_skills: tuple[str, ...] = ()
    candidates: tuple[ScoredCandidate, ...] = ()
    chosen: tuple[ScoredCandidate, ...] = ()
    screened_out: tuple[ScreeningOutcome, ...] = ()
    source_status: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        return (
            f"intent={self.intent!r} candidates={len(self.candidates)} "
            f"chosen={len(self.chosen)} screened_out={len(self.screened_out)} "
            f"sources={self.source_status}"
        )


# ── 检索源 ───────────────────────────────────────────────────────────────


class SkillSource(ABC):
    """一个技能来源。search() 只做检索, **不做准入判断** —— 那是闸门的事。"""

    name: str = "source"

    @abstractmethod
    def search(self, query: SearchQuery) -> list[SkillCandidate]:
        """返回候选。查不到返回空列表, 不抛 —— 一个源挂了不该让整次发现失败。"""

    @property
    def last_error(self) -> str:
        return getattr(self, "_last_error", "")


# 技能包目录约定的两处元数据来源
_MANIFEST_SKILLS_RE = re.compile(r"^([A-Za-z0-9_]+)\s*=\s*\{([^}]*)\}", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> dict[str, str]:
    """解析 SKILL.md 的 YAML frontmatter。

    只认 `key: value` 这种平面结构, 不引入 yaml 依赖 —— frontmatter 里
    真正会被用到的只有 name / description / license 这几个标量字段。
    """
    m = _FRONTMATTER_RE.match(text)
    if m is None:
        return {}
    out: dict[str, str] = {}
    for raw in m.group(1).splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        out[key.strip().lower()] = val.strip().strip("'\"")
    return out


def _parse_pack_skills(manifest_text: str) -> dict[str, str]:
    """从 manifest.toml 的 [skills] 段抠出 name -> "module:Class"。

    不用 tomllib 重解一遍: 这里只需要 name 与 class 的对应, 而 class 值里
    的 `file = "x.py:Class"` 形态要求我们把 file 段切出模块路径。
    """
    out: dict[str, str] = {}
    in_skills = False
    for raw in manifest_text.splitlines():
        line = raw.strip()
        if line.startswith("["):
            in_skills = line == "[skills]"
            continue
        if not in_skills or not line or line.startswith("#"):
            continue
        name, _, rest = line.partition("=")
        name = name.strip()
        file_m = re.search(r'file\s*=\s*"([^"]+)"', rest)
        class_m = re.search(r'class\s*=\s*"([^"]+)"', rest)
        if file_m is None or class_m is None:
            continue
        # "ppt_pack/skills/outline.py:OutlineSkill" -> "ppt_pack.skills.outline:OutlineSkill"
        filepart = file_m.group(1)
        mod = filepart.split(":")[0].removesuffix(".py").replace("/", ".")
        out[name] = f"{mod}:{class_m.group(1)}"
    return out


class LocalPackSource(SkillSource):
    """扫本地技能包目录。第一方来源 —— 内容在版本控制里, 有人看过。"""

    name = "local_pack"

    def __init__(self, packs_dir: Path | str) -> None:
        self._dir = Path(packs_dir)

    def search(self, query: SearchQuery) -> list[SkillCandidate]:
        out: list[SkillCandidate] = []
        if not self._dir.is_dir():
            self._last_error = f"packs dir not found: {self._dir}"
            return out
        for pack in sorted(p for p in self._dir.iterdir() if p.is_dir()):
            manifest_path = pack / "manifest.toml"
            if not manifest_path.is_file():
                continue
            try:
                text = manifest_path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                self._last_error = f"unreadable manifest: {pack.name} ({exc})"
                continue
            pack_m = re.search(r'name\s*=\s*"([^"]+)"', text)
            desc_m = re.search(r'description\s*=\s*"([^"]+)"', text)
            pack_desc = desc_m.group(1) if desc_m else ""
            src_dir = pack / "src"
            for skill_name, import_path in _parse_pack_skills(text).items():
                out.append(
                    SkillCandidate(
                        name=skill_name,
                        kind="local_pack",
                        source=self.name,
                        description=f"{pack_desc} [{pack_m.group(1) if pack_m else pack.name}]",
                        tags=(pack.name.replace("_pack", ""),),
                        trust=TrustLevel.FIRST_PARTY,
                        root=pack,
                        import_path=import_path,
                        sys_path=str(src_dir) if src_dir.is_dir() else "",
                    )
                )
            # 兼容 Agent Skills 事实标准: 带 SKILL.md 的目录也认
            skill_md = pack / "SKILL.md"
            if skill_md.is_file():
                try:
                    fm = _parse_frontmatter(skill_md.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    fm = {}
                if fm.get("name"):
                    out.append(
                        SkillCandidate(
                            name=fm["name"],
                            kind="local_pack",
                            source=self.name,
                            description=fm.get("description", ""),
                            tags=(pack.name.replace("_pack", ""), "skill_md"),
                            trust=TrustLevel.FIRST_PARTY,
                            root=pack,
                        )
                    )
        return out


class PoolSource(SkillSource):
    """已在池中的技能。避免同一个能力被重复发现/重复注册。"""

    name = "pool"

    def __init__(self, pool: SkillPool) -> None:
        self._pool = pool

    def search(self, query: SearchQuery) -> list[SkillCandidate]:
        out: list[SkillCandidate] = []
        for name in self._pool.list_available():
            manifest = self._pool.get_manifest(name) or {}
            out.append(
                SkillCandidate(
                    name=name,
                    kind="pool",
                    source=self.name,
                    description=str(manifest.get("description", "")),
                    tags=tuple(manifest.get("tags", ()) or ()),
                    trust=TrustLevel.FIRST_PARTY,
                    root=None,
                )
            )
        return out


class EntryPointSource(SkillSource):
    """第三方技能包: 通过 Python entry_points 机制声明。

    pyproject.toml 里已经预留了 `[project.entry-points."hiveswarm.skills"]`,
    这里把它兑现 —— 别人 `pip install hiveswarm-skill-xxx` 之后能被自动发现,
    不需要改本仓库任何代码。用标准机制而不是自造插件协议。
    """

    name = "entry_point"

    def __init__(self, group: str = "hiveswarm.skills") -> None:
        self._group = group

    def _iter_entries(self) -> list[Any]:
        try:
            from importlib.metadata import entry_points
        except ImportError:  # pragma: no cover - py>=3.8 always has it
            return []
        try:
            eps = entry_points()
            found = eps.select(group=self._group) if hasattr(eps, "select") else eps.get(self._group, [])
            return list(found)
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"entry_points lookup failed: {exc}"
            return []

    def search(self, query: SearchQuery) -> list[SkillCandidate]:
        out: list[SkillCandidate] = []
        for ep in self._iter_entries():
            out.append(
                SkillCandidate(
                    name=ep.name,
                    kind="entry_point",
                    source=self.name,
                    description=f"third-party skill via entry point {ep.value!r}",
                    tags=("third_party",),
                    # 第三方入口: 内容不在本地目录, 按未验证处理, 由闸门决定去向
                    trust=TrustLevel.UNVERIFIED,
                    root=None,
                    import_path=ep.value,
                )
            )
        return out


class GitHubRepoSource(SkillSource):
    """GitHub 官方 Search API 检索技能仓库。

    走官方 REST(+ 可选 token), 不自己爬页面。**任何失败都降级成空结果**:
    限流、断网、无 token、API 改版 —— 都不该让本地发现流程挂掉。
    诊断信息放 last_error, 不抛。
    """

    name = "github"
    API_URL = "https://api.github.com/search/repositories"

    def __init__(
        self,
        *,
        topic: str = "claude-skill",
        token: str | None = None,
        per_page: int = 5,
        timeout_s: float = 8.0,
        enabled: bool = True,
        client: Any | None = None,
    ) -> None:
        self._topic = topic
        self._token = token
        self._per_page = per_page
        self._timeout = timeout_s
        self._enabled = enabled
        self._client = client
        self._last_error = ""

    def _headers(self) -> dict[str, str]:
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hiveswarm-skill-discovery",
        }
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _build_query(self, query: SearchQuery) -> str:
        parts: list[str] = [f"topic:{self._topic}"]
        for t in query.tags[:2]:
            t = t.strip().replace(" ", "-")
            if t and t != self._topic:
                parts.append(f"topic:{t}")
        if query.required_skills:
            parts.append(query.required_skills[0])
        parts.append("language:Python")
        return " ".join(parts)

    def search(self, query: SearchQuery) -> list[SkillCandidate]:
        out: list[SkillCandidate] = []
        self._last_error = ""
        if not self._enabled:
            self._last_error = "disabled by config"
            return out
        try:
            import httpx
        except ImportError as exc:
            self._last_error = f"httpx not available: {exc}"
            return out

        params = {
            "q": self._build_query(query),
            "sort": "stars",
            "order": "desc",
            "per_page": str(self._per_page),
        }
        try:
            if self._client is not None:
                resp = self._client.get(self.API_URL, params=params, headers=self._headers())
            else:
                with httpx.Client(timeout=self._timeout, follow_redirects=True) as cli:
                    resp = cli.get(self.API_URL, params=params, headers=self._headers())
            if resp.status_code != 200:
                self._last_error = f"HTTP {resp.status_code}: {resp.text[:120]}"
                return out
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 - 检索失败不等于发现失败
            self._last_error = f"{type(exc).__name__}: {exc}"
            _log.info("github search unavailable: %s", self._last_error)
            return out

        for item in payload.get("items", []) or []:
            full = str(item.get("full_name", ""))
            if not full:
                continue
            out.append(
                SkillCandidate(
                    name=full.split("/")[-1],
                    kind="github_repo",
                    source=self.name,
                    description=str(item.get("description") or ""),
                    tags=tuple(str(t) for t in (item.get("topics") or [])),
                    trust=TrustLevel.UNVERIFIED,
                    root=None,  # 内容不在本地 -> 无法准入 -> 不能自动装配
                    remote_url=str(item.get("html_url") or ""),
                    stars=int(item.get("stargazers_count") or 0),
                )
            )
        return out


# ── 打分 ─────────────────────────────────────────────────────────────────


def _tokens(text: str) -> set[str]:
    """中英混排分词。中文没有空格, 用二元组 —— 对本场景足够且零依赖。"""
    low = text.lower()
    out: set[str] = set(re.findall(r"[a-z0-9_]{2,}", low))
    for run in re.findall(r"[\u4e00-\u9fff]+", low):
        if len(run) == 1:
            out.add(run)
        for i in range(len(run) - 1):
            out.add(run[i : i + 2])
    return out


def score_candidate(
    cand: SkillCandidate,
    query: SearchQuery,
    *,
    health: float = 1.0,
    weights: dict[str, float] | None = None,
) -> ScoredCandidate:
    """给一个候选打分, 返回逐项 breakdown。

    分数只用于**排序**, 不用于判断可信 —— 排序第一的候选照样要过闸门。
    """
    w = weights or _DEFAULT_WEIGHTS
    breakdown: dict[str, float] = {}

    # 1. 显式声明命中(Plan 里写了这个技能名)
    if query.required_skills:
        name_hit = 1.0 if cand.name in query.required_skills else 0.0
    else:
        name_hit = 0.0
    breakdown["name"] = name_hit

    # 2. 标签重叠
    q_tags = {t.lower() for t in query.tags}
    c_tags = {t.lower() for t in cand.tags}
    breakdown["tag"] = (len(q_tags & c_tags) / len(q_tags)) if q_tags else 0.0

    # 3. 意图文本 vs 候选文本(描述 + 名字 + 标签)
    q_tok = _tokens(query.intent)
    c_tok = _tokens(f"{cand.name} {cand.description} {' '.join(cand.tags)}")
    breakdown["text"] = (len(q_tok & c_tok) / len(q_tok)) if q_tok else 0.0

    # 4. 来源可信度(排序参考, 不等于放行)
    breakdown["trust"] = _SOURCE_WEIGHT.get(cand.trust, 0.0)

    # 5. 历史健康度(来自 Pool 的巡检)
    breakdown["health"] = max(0.0, min(1.0, health))

    total = sum(breakdown[k] * w.get(k, 0.0) for k in breakdown)
    # 名字命中是硬信号: 直接压过其余项, 避免被无关标签稀释
    if name_hit:
        total = max(total, 0.9)
    return ScoredCandidate(candidate=cand, score=round(total, 4), breakdown=breakdown)


# ── 发现编排 ─────────────────────────────────────────────────────────────


class SkillDiscovery:
    """编排: 多源检索 -> 打分排序 -> 过准入闸门 -> 给出可装配集。"""

    def __init__(
        self,
        sources: list[SkillSource],
        gate: AdmissionGate,
        *,
        pool: SkillPool | None = None,
        bus: EventBus | None = None,
        weights: dict[str, float] | None = None,
    ) -> None:
        if not sources:
            raise ValueError("SkillDiscovery needs at least one source")
        self._sources = list(sources)
        self._gate = gate
        self._pool = pool
        self._bus = bus
        self._weights = weights or _DEFAULT_WEIGHTS
        # 单次 discover() 内的包级判决缓存。见 screen(): 准入粒度是**包**,
        # 一个包提供 N 个技能时不该把同一个包扫 N 遍。
        self._screen_cache: dict[str, ScreeningOutcome] = {}

    # ── 主流程 ───────────────────────────────────────────────────────────

    def discover(
        self,
        intent: str,
        required_skills: tuple[str, ...] = (),
        *,
        tags: tuple[str, ...] = (),
    ) -> DiscoveryResult:
        """检索 -> 打分 -> 筛查。**不裁剪结果**: chosen 是"允许装配的全集",
        想限制这次装几个, 用 install_selected(top_k=N)。
        裁剪留在筛查阶段会让"过闸了却没被列出来"变成一个说不清的状态。
        """
        query = SearchQuery(
            intent=intent, required_skills=tuple(required_skills), tags=tuple(tags)
        )
        # 缓存只活在一次发现里: 跨调用复用会变成"拿旧结论当放行凭证"。
        self._screen_cache.clear()
        raw: list[SkillCandidate] = []
        status: dict[str, str] = {}
        for src in self._sources:
            try:
                found = src.search(query)
            except Exception as exc:  # noqa: BLE001 - 单源失败不拖垮整体
                status[src.name] = f"error: {type(exc).__name__}: {exc}"
                continue
            status[src.name] = f"ok: {len(found)}" if found else (src.last_error or "ok: 0")
            raw.extend(found)
            self._emit_discovered(src.name, found)

        # 同名去重: 本地源优先(内容在版本控制里, 可信度更高)
        deduped: dict[str, SkillCandidate] = {}
        for cand in raw:
            prev = deduped.get(cand.name)
            if prev is None or _SOURCE_WEIGHT[cand.trust] > _SOURCE_WEIGHT[prev.trust]:
                deduped[cand.name] = cand

        scored = [
            score_candidate(c, query, health=self._health_of(c.name), weights=self._weights)
            for c in deduped.values()
        ]
        scored.sort(key=lambda s: (-s.score, s.name))

        chosen: list[ScoredCandidate] = []
        screened_out: list[ScreeningOutcome] = []
        for s in scored:
            outcome = self.screen(s.candidate)
            if outcome.selected:
                chosen.append(s)
            else:
                screened_out.append(outcome)

        self._emit_screened(chosen, screened_out)
        return DiscoveryResult(
            intent=intent,
            required_skills=tuple(required_skills),
            candidates=tuple(scored),
            chosen=tuple(chosen),
            screened_out=tuple(screened_out),
            source_status=status,
        )

    def _health_of(self, name: str) -> float:
        if self._pool is None:
            return 1.0
        report = self._pool.health_report().get(name)
        if not report:
            return 1.0
        return 1.0 - float(report.get("health", {}).get("error_rate", 0.0))

    # ── 筛查(过闸门) ──────────────────────────────────────────────────────

    def screen(self, cand: SkillCandidate) -> ScreeningOutcome:
        """把候选送进准入闸门。

        三个刻意的行为:
          - `needs_fetch` 的远程候选 **不构造 subject 直接判留观**: 本地没有内容
            可扫, 让规则去猜等于用"没扫到"冒充"没问题".
          - `kind == "pool"` 的直接放行: 已经在池里, 说明它当初已经过过闸,
            重复审只会让每次发现都变慢(闸门不是装饰品, 但也不该被复用成空转).
          - 同包候选复用一次判决: 准入粒度和 manifest/目录扫描的粒度一样是**包**,
            ppt_pack 一个包出 4 个技能, 扫 4 遍纯属浪费.
        """
        if cand.kind == "pool":
            return ScreeningOutcome(
                cand.name, Verdict.ALLOW, "已在池中(先前已过闸), 无需重启同一进程内的重复审查"
            )
        if cand.needs_fetch:
            return ScreeningOutcome(
                cand.name,
                Verdict.QUARANTINE,
                "远程候选未取回本地, 无可扫描内容; 按 fail-closed 留观, "
                "须人工取回后重新过闸才可装配",
            )
        key = self._cache_key(cand)
        cached = self._screen_cache.get(key)
        if cached is not None:
            return ScreeningOutcome(cand.name, cached.verdict, cached.reason, cached.rule_ids)
        subject = self.to_subject(cand)
        report = self._gate.admit(subject)
        rules = tuple(sorted({f.rule_id for f in report.findings}))
        reason = (
            f"准入判决 {report.verdict.value} (trust={report.trust.value}, "
            f"files={report.files_scanned})"
        )
        if rules:
            reason += f"; 命中 {', '.join(rules)}"
        outcome = ScreeningOutcome(cand.name, report.verdict, reason, rules)
        self._screen_cache[key] = outcome
        return outcome

    @staticmethod
    def _cache_key(cand: SkillCandidate) -> str:
        if cand.root is None:
            return f"volatile:{cand.name}"
        try:
            root = str(cand.root.resolve())
        except OSError:  # pragma: no cover - 极少数不可解析路径
            root = str(cand.root)
        return f"{root}|{cand.trust.value}"

    @staticmethod
    def to_subject(cand: SkillCandidate) -> AdmissionSubject:
        """候选 -> 准入入参。这是两个模块之间唯一的耦合点。"""
        if cand.root is not None:
            return AdmissionSubject.from_pack_dir(
                cand.root, trust=cand.trust, source_kind=cand.kind
            )
        return AdmissionSubject(
            name=cand.name,
            trust=cand.trust,
            source_root=None,
            source_kind=cand.kind,
            remote_url=cand.remote_url,
        )

    # ── 装配 ─────────────────────────────────────────────────────────────

    def install_selected(
        self,
        result: DiscoveryResult,
        *,
        top_k: int | None = None,
        only: tuple[str, ...] | None = None,
    ) -> tuple[str, ...]:
        """把 chosen 里的候选注册进池。**唯一装配入口**。

        两个筛选参数语义不同, 别混用:
          - `only`  = 只要这些**名字** —— Plan 明确声明了 required_skills 时用这个;
          - `top_k` = 分数最高的前 K 个 —— 探索性场景(不预设技能名)才用。
        两个都给时 `only` 优先: "计划要什么"比"分数高什么"更有约束力。

        装配前会**再判一次**(不是复用筛选时的结论): 发现与装配之间可能隔着
        下载、人审、时间流逝 —— 拿旧结论当放行凭证是典型 TOCTOU。
        """
        if self._pool is None:
            raise ValueError("install_selected requires a pool")
        installed: list[str] = []
        if only is not None:
            wanted = set(only)
            targets = [s for s in result.chosen if s.name in wanted]
        elif top_k is None:
            targets = list(result.chosen)
        else:
            targets = list(result.chosen[:top_k])
        for scored in targets:
            cand = scored.candidate
            if cand.kind == "pool" or not cand.import_path:
                continue
            if cand.needs_fetch:
                _log.warning("skip %s: remote candidate without local content", cand.name)
                continue
            subject = self.to_subject(cand)
            try:
                skill = self._gate.register_if_admitted(
                    self._pool, subject, self._make_factory(cand)
                )
                installed.append(skill.manifest.name)
            except Exception as exc:  # noqa: BLE001 - 单条装不上不该中断其余
                _log.warning("install %s failed: %s", cand.name, exc)
        return tuple(installed)

    @staticmethod
    def _make_factory(cand: SkillCandidate) -> Callable[[], Skill]:
        def factory() -> Skill:
            if cand.sys_path and cand.sys_path not in sys.path:
                sys.path.insert(0, cand.sys_path)
            mod_name, _, cls_name = cand.import_path.partition(":")
            if not mod_name or not cls_name:
                raise ValueError(f"bad import_path: {cand.import_path!r}")
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, cls_name)
            obj = cls()
            if not isinstance(obj, Skill):
                raise TypeError(f"{cand.import_path} is not a Skill: {type(obj).__name__}")
            return obj

        return factory

    # ── 事件 ─────────────────────────────────────────────────────────────

    def _emit_discovered(self, source: str, found: list[SkillCandidate]) -> None:
        if self._bus is None or not found:
            return
        try:
            from core.events import Event, EventType

            self._bus.publish(
                Event(
                    type=EventType.SKILL_DISCOVERED,
                    payload={"source": source, "names": [c.name for c in found]},
                )
            )
        except Exception:  # noqa: BLE001
            _log.warning("emit discovered event failed", exc_info=True)

    def _emit_screened(
        self, chosen: list[ScoredCandidate], out: list[ScreeningOutcome]
    ) -> None:
        if self._bus is None:
            return
        try:
            from core.events import Event, EventType

            self._bus.publish(
                Event(
                    type=EventType.SKILL_SCREENED,
                    payload={
                        "chosen": [s.name for s in chosen],
                        "screened_out": [
                            {"name": o.name, "verdict": o.verdict.value} for o in out
                        ],
                    },
                )
            )
        except Exception:  # noqa: BLE001
            _log.warning("emit screened event failed", exc_info=True)


def build_default_discovery(
    *,
    packs_dir: Path | str,
    pool: SkillPool | None = None,
    gate: AdmissionGate | None = None,
    bus: EventBus | None = None,
    github_enabled: bool = False,
    github_token: str | None = None,
) -> SkillDiscovery:
    """组装一个默认发现器。本地源默认开, GitHub 源默认关。

    GitHub 默认关的理由: 它是**远程候选**, 本地没内容 -> 必然留观, 开不开都
    装不上任何东西; 默认关掉可以避免在网络受限的环境里白等 8 秒超时。
    想用的人显式打开, 也知道自己拿到的是"候选"而不是"技能"。
    """
    import os

    sources: list[SkillSource] = [LocalPackSource(packs_dir)]
    if pool is not None:
        sources.append(PoolSource(pool))
    sources.append(EntryPointSource())
    if github_enabled:
        sources.append(
            GitHubRepoSource(token=github_token or os.getenv("GITHUB_TOKEN"))
        )
    return SkillDiscovery(
        sources,
        gate or AdmissionGate(bus=bus),
        pool=pool,
        bus=bus,
    )
