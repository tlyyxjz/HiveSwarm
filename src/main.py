"""HiveSwarm 顶层入口.

用法:
  python -m src.main "帮我做一个 PPT"

内部:
  1. 解析命令行 (用户输入)
  2. 构造 Services (MVP 全 stub)
  3. Brain.plan 拆任务
  4. Work 借/装/跑/还
  5. Inspect 校验
  6. 输出结果
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from layers.brain.planner import MockBrain
from layers.memory.store import MemoryStore, MemoryTier
from layers.report import ReportGenerator
from layers.work.factory import AgentFactory
from layers.work.pool import SkillPool
from layers.work.skill_registry import (
    register_needed_skills,
    register_needed_skills_via_discovery,
)
from layers.work.transaction import TaskTransaction
from stub.bus_local import LocalEventBus
from stub.services import build_default_services
from stub.store_sqlite import SQLiteStore

_log = logging.getLogger(__name__)


def run_demo(
    request: str,
    runtime_dir: str = "~/.hiveswarm",
    target: str | None = None,
    *,
    use_discovery: bool = False,
) -> dict[str, Any]:
    """跑一次 demo 任务, 返回结果 dict. 给 main 和测试共用.

    use_discovery=True 时走 M5 发现 + M4 准入的新装配路径(见
    layers/work/skill_registry.py)。默认 False = 旧路径, 行为一字不变。
    """
    runtime = Path(runtime_dir).expanduser()
    runtime.mkdir(parents=True, exist_ok=True)

    # 1. 构造 Services (本函数只用它初始化的副作用, 不持有返回值)
    build_default_services()
    # 2. 构造 bus + pool + brain
    bus = LocalEventBus()
    pool = SkillPool(bus=bus)
    brain = MockBrain()
    factory = AgentFactory(pool)
    memory = MemoryStore(SQLiteStore(runtime / "memory.db"))

    # 3. 拆任务
    plan = asyncio.run(brain.plan(request))
    # 4. 注册 plan 需要的 skill
    registration: dict[str, Any] | None = None
    if use_discovery:
        report = register_needed_skills_via_discovery(pool, plan, bus=bus)
        registration = report.to_dict()
        if not report.ok:
            _log.warning(
                "发现+准入之后仍有缺口: missing=%s mocked=%s", report.missing, report.mocked
            )
    else:
        register_needed_skills(pool, plan)

    # 5. 跑事务
    final = {
        "task_id": plan.task_id,
        "request": request,
        "rationale": plan.rationale,
        "subtasks": [s.sub_id for s in plan.subtasks],
        "results": [],
    }
    if registration is not None:
        final["registration"] = registration

    with TaskTransaction(pool, factory, plan.task_id) as tx:
        for sub in plan.subtasks:
            # scan 子任务: 用 target
            req = sub.required_skills
            if any(s.startswith("agentvet_") for s in req):
                inp = {"target": target or "."}
            elif any(s == "outline" for s in req):
                inp = {"facts": ["a", "b", "c"]}
            elif any(s == "export" for s in req):
                inp = {"layouts": ["title", "content"]}
            else:
                inp = {"topic": request}
            r = tx.add(sub).run(inp)
            final["results"].append(
                {"sub_id": r.sub_id, "ok": r.ok, "error": r.error, "result": r.result}
            )

    final["all_ok"] = tx._result.all_ok
    final["success_count"] = tx._result.success_count
    final["fail_count"] = tx._result.fail_count

    # 6. 存 memory
    memory.put(MemoryTier.LONG, f"task:{plan.task_id}", final)

    # 7. 生成详细报告 (Markdown + PDF)
    try:
        report_gen = ReportGenerator(bus=bus, memory=memory, reports_dir=str(runtime / "reports"))
        report = report_gen.generate(
            task_id=plan.task_id,
            request=request,
            result=final,
            title=f"HiveSwarm 任务报告 · {plan.task_id}",
        )
        final["report_md"] = str(report.md_path)
        final["report_pdf"] = str(report.pdf_path) if report.pdf_path else None
    except Exception as exc:  # noqa: BLE001
        # 报告失败不影响主流程
        _log.warning("ReportGenerator failed: %s", exc)
        final["report_md"] = None
        final["report_pdf"] = None

    return final


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HiveSwarm MVP demo runner")
    parser.add_argument("request", nargs="?", default="帮我做一个 PPT", help="用户的自然语言请求")
    parser.add_argument("--runtime", default="~/.hiveswarm", help="运行时数据目录")
    parser.add_argument("--target", default=None, help="扫描目标路径(用于 '扫描' 请求)")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument(
        "--discovery",
        action="store_true",
        help="走 M5 技能发现 + M4 准入闸门装配技能(默认走旧路径)",
    )
    args = parser.parse_args(argv)

    # 扫描请求: 把 target 注入到 plan input
    target = args.target
    result = run_demo(
        args.request, args.runtime, target=target, use_discovery=args.discovery
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Task ID: {result['task_id']}")
        print(f"Rationale: {result['rationale']}")
        print(f"Subtasks ({len(result['subtasks'])}): {', '.join(result['subtasks'])}")
        print(f"Result: {'[OK] all passed' if result['all_ok'] else '[FAIL] some failed'}")
        print(f"  success: {result['success_count']} / fail: {result['fail_count']}")
        reg = result.get("registration")
        if reg:
            print(f"  skills installed: {', '.join(reg['installed']) or '(none)'}")
            if reg["missing"]:
                print(f"  [WARN] missing: {', '.join(reg['missing'])}")
            if reg["mocked"]:
                print(f"  [WARN] mock fallback: {', '.join(reg['mocked'])}")
        for r in result["results"]:
            mark = "[OK]" if r["ok"] else "[FAIL]"
            err = f" ({r['error']})" if r["error"] else ""
            print(f"  {mark} {r['sub_id']}{err}")

    return 0 if result["all_ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
