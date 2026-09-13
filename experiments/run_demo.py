"""run_demo — 战役 2 的端到端联调入口.

跑什么: 30 题 × 3 组 × (干净 + 可适用注入) ≈ 全量 mock 联调.
产出: tasks/*.json (任务集交付物) + runs/demo/*.json (轨迹) + report.md.
用法:
    python experiments/run_demo.py            # 全量 mock 联调
    python experiments/run_demo.py --subset 3 # 每类抽 3 题 (冒烟)
真实实验 (用户亲自跑, 不在本脚本): runner.run_batch + modelscope 适配器.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from experiments.runner import run_batch
from experiments.taskset import TASKS, gen_tasks, validate
from experiments.inject import INJECTIONS


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", type=int, default=0, help="每类抽 N 题 (0=全量)")
    ap.add_argument("--outdir", type=str, default="experiments/runs/demo")
    args = ap.parse_args(argv)

    val = validate()
    print(f"[taskset] total={val['total']} categories={val['categories']} "
          f"criteria_compilable={val['criteria_compilable']}/{val['criteria_total']} "
          f"problems={val['problems']}")
    if val["problems"]:
        return 2

    out_dir = Path(args.outdir)
    gen_tasks(Path("experiments/tasks"))
    print(f"[tasks] 30 个 JSON 已落盘 experiments/tasks/")

    task_ids = [t["id"] for t in TASKS]
    if args.subset:
        picked = []
        for cat in ("serial", "branch", "guard"):
            picked += [t["id"] for t in TASKS if t["category"] == cat][: args.subset]
        task_ids = picked
    injections = sorted(INJECTIONS)
    print(f"[runner] {len(task_ids)} 题 × 3 组 × (clean+适用注入 {len(injections)}) ...")

    traces = run_batch(task_ids, ["A", "B", "C"], out_dir, injections=injections)
    ok = sum(1 for t in traces if t.success)
    print(f"[runner] traces={len(traces)} success={ok} -> {out_dir}/")

    from experiments.report import write_report

    rp = write_report(traces, out_dir / "report.md", demo=True, run_dir=str(out_dir))
    print(f"[report] {rp}")
    print("\n—— 摘要 (演示数据, 非实测) ——")
    by_group: dict[str, list] = {}
    for t in traces:
        by_group.setdefault(t.group, []).append(t)
    for g in ("A", "B", "C"):
        ts = by_group.get(g, [])
        print(f"  {g}: {sum(1 for t in ts if t.success)}/{len(ts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
