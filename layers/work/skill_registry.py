"""Skill registry utilities - central skill registration logic.

Extracted from src/main.py to share between CLI and gateway implementations.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from core.skill import Skill, SkillManifest
from layers.work.discovery import build_default_discovery
from layers.work.pool import SkillPool

if TYPE_CHECKING:
    from core.brain import Plan
    from core.events import EventBus
    from layers.work.admission import AdmissionGate

_log = logging.getLogger(__name__)


# 计划关键词 → 技能名映射
_PLAN_TO_SKILLS = {
    "data_collect", "outline", "layout", "export",
    "agentvet_l1", "agentvet_l2", "agentvet_l3", "agentvet_l4",
    "web_search",
}


class _EchoSkill(Skill):
    """内置 mock skill, 让 demo 跑得起来."""

    def __init__(self, name: str) -> None:
        super().__init__(SkillManifest(name=name, api_version="1.0"))

    def run(self, input_data: dict) -> dict:
        return {"by": self.manifest.name, "echo": input_data, "ok": True}


def _try_register_real_skill(pool: SkillPool, name: str) -> bool:
    """尝试从真技能包注册. 成功返回 True.

    当前支持的包:
      - agentvet_l1/l2/l3/l4 → agentvet_pack (示例: AI 安全扫描)
      - http_fetch/url_extract/http_post → crawler_pack (通用 HTTP)
    """
    try:
        from pathlib import Path
        if name.startswith("agentvet_"):
            _pack_src = Path(__file__).parent.parent.parent / "skills" / "agentvet_pack" / "src"
            cls_map = {
                "agentvet_l1": "ScanL1Skill", "agentvet_l2": "ScanL2Skill",
                "agentvet_l3": "ScanL3Skill", "agentvet_l4": "ScanL4Skill",
            }
            module_name = "agentvet_pack.skills"
        elif name.startswith("http_") or name == "url_extract":
            _pack_src = Path(__file__).parent.parent.parent / "skills" / "crawler_pack" / "src"
            cls_map = {
                "http_fetch": "HttpFetchSkill",
                "url_extract": "UrlExtractSkill",
                "http_post": "HttpPostSkill",
            }
            module_name = "crawler_pack.skills"
        elif name in ("data_collect", "outline", "layout", "export"):
            _pack_src = Path(__file__).parent.parent.parent / "skills" / "ppt_pack" / "src"
            cls_map = {
                "data_collect": "DataCollectSkill",
                "outline": "OutlineSkill",
                "layout": "LayoutSkill",
                "export": "ExportSkill",
            }
            module_name = "ppt_pack.skills"
        elif name == "web_search":
            _pack_src = Path(__file__).parent.parent.parent / "skills" / "web_search_pack" / "src"
            cls_map = {"web_search": "WebSearchSkill"}
            module_name = "web_search_pack"
        else:
            return False

        if str(_pack_src) not in sys.path:
            sys.path.insert(0, str(_pack_src))

        import importlib
        mod = importlib.import_module(module_name)
        cls_name = cls_map.get(name)
        if cls_name is None or not hasattr(mod, cls_name):
            return False
        cls = getattr(mod, cls_name)
        pool.register(cls())
        return True
    except Exception as exc:  # noqa: BLE001
        _log.warning("real skill %s load failed: %s", name, exc)
        return False


def register_needed_skills(pool: SkillPool, plan: Plan) -> None:
    """根据 plan 里的 required_skills 注册实现. 优先真技能包, 失败回 mock.

    Args:
        pool: SkillPool to register skills into
        plan: Plan containing subtasks with required_skills

    ⚠️ 这条是**旧路径**, 未接准入闸门(见 docs/任务单_T16 非目标)。保留它是为了
    不破坏既有调用方; 新代码请用下面的 register_needed_skills_via_discovery()。
    """
    seen: set[str] = set()
    for sub in plan.subtasks:
        for s in sub.required_skills:
            if s in seen:
                continue
            # 先试真技能包, 失败回 mock
            if not _try_register_real_skill(pool, s):
                pool.register(_EchoSkill(s))
            seen.add(s)


# ── M5 发现 + M4 准入 接线 (T1.6 第二步) ─────────────────────────────────


@dataclass(frozen=True)
class RegisterReport:
    """一次"按 plan 装配技能"的结果。**缺什么必须能看见**。

    旧路径的做法是: 找得到真技能就注册, 找不到就造一个 _EchoSkill 塞进去。
    那个兜底在 demo 里很方便, 但它把"这个能力其实不存在"藏进了一个副作用里 ——
    调用方看到的只是"注册完了, 没报错"。

    本报告把三件事分开列: 要什么(needed) / 真装上了什么(installed) /
    没装上什么(missing)。missing 非空就是缺口, 由调用方决定怎么办,
    而不是在这里悄悄补一个假的。
    """

    needed: tuple[str, ...]
    installed: tuple[str, ...]
    missing: tuple[str, ...]
    mocked: tuple[str, ...] = ()
    screened_out: tuple[tuple[str, str, str], ...] = ()  # (name, verdict, reason)
    source_status: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """真技能是否都装上了(mock 回落不算 ok)。"""
        return not self.missing and not self.mocked

    def to_dict(self) -> dict:
        return {
            "needed": list(self.needed),
            "installed": list(self.installed),
            "missing": list(self.missing),
            "mocked": list(self.mocked),
            "screened_out": [
                {"name": n, "verdict": v, "reason": r} for n, v, r in self.screened_out
            ],
            "sources": dict(self.source_status),
        }


def _default_packs_dir() -> Path:
    return Path(__file__).parent.parent.parent / "skills"


def _collect_required(plan: Plan) -> tuple[str, ...]:
    """按出现顺序去重 —— 顺序稳定, 报告才能逐次 diff。"""
    seen: dict[str, None] = {}
    for sub in plan.subtasks:
        for s in sub.required_skills:
            seen.setdefault(s, None)
    return tuple(seen)


def register_needed_skills_via_discovery(
    pool: SkillPool,
    plan: Plan,
    *,
    packs_dir: Path | str | None = None,
    gate: AdmissionGate | None = None,
    bus: EventBus | None = None,
    github_enabled: bool = False,
    allow_mock_fallback: bool = False,
) -> RegisterReport:
    """按 plan 装配技能: 检索 -> 打分 -> 过准入闸门 -> 装配。

    与旧 register_needed_skills() 的三点差别:
      1. 不再走硬编码映射表, 而是从技能包 manifest 检索出候选 (M5);
      2. 每个包**装配前过准入闸门**, 不过闸的一律不装 (M4);
      3. **找不到不造假**: 默认不塞 _EchoSkill, 缺口原样报回给调用方。
         需要旧行为时显式传 allow_mock_fallback=True —— 让"我在用假技能"
         成为一个必须打出来的开关, 而不是默认的静默兜底。

    幂等: 池里已有的技能不再重复审, 所以同一进程内多次调用不会把包反复扫。
    """
    needed = _collect_required(plan)
    already = set(pool.list_available())
    todo = tuple(n for n in needed if n not in already)
    if not todo:
        return RegisterReport(
            needed=needed,
            installed=(),
            missing=(),
            source_status={"discovery": "skipped: all required skills already in pool"},
        )

    discovery = build_default_discovery(
        packs_dir=packs_dir or _default_packs_dir(),
        pool=pool,
        gate=gate,
        bus=bus,
        github_enabled=github_enabled,
    )
    result = discovery.discover(plan.original_request, todo)
    installed = discovery.install_selected(result, only=todo)

    still = [n for n in todo if n not in set(installed)]
    mocked: tuple[str, ...] = ()
    if still and allow_mock_fallback:
        for n in still:
            pool.register(_EchoSkill(n))
        mocked = tuple(still)
        _log.warning(
            "discovery 未装上的技能已回落 mock(EchoSkill): %s —— mock 只回显输入, "
            "不具备真实能力, 对外不要当真的用",
            list(still),
        )
    elif still:
        _log.warning("discovery 未装上的技能(未回落 mock, 如实上报): %s", list(still))

    wanted = set(todo)
    return RegisterReport(
        needed=needed,
        installed=installed,
        missing=tuple(n for n in still if n not in set(mocked)),
        mocked=mocked,
        screened_out=tuple(
            (o.name, o.verdict.value, o.reason)
            for o in result.screened_out
            if o.name in wanted
        ),
        source_status=dict(result.source_status),
    )
