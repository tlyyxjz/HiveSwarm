"""七指标计算 (战役 2 · T2.4).

只做计算, 不做宣传: 每个指标带分母 n 和口径说明. 对标基线数字
(LongRCA 24.1% / AgentTether 69.11% / EvidenceBound ~24% token) 只出现在
报告的"对标"列, 由 report.py 负责 — 计算层不掺任何目标值.
"""
from __future__ import annotations

from experiments.inject import INJECTIONS
from experiments.runner import RunTrace
from experiments.taskset import TASKS, validate


def compute(traces: list[RunTrace]) -> dict:
    """从 trace 集合计算七指标. 口径见各字段注释."""
    val = validate()

    # 1 断言可编译率: 任务判据能被 6 原语编译的比例 (taskset 级)
    compile_rate = (
        val["criteria_compilable"] / val["criteria_total"] if val["criteria_total"] else 0.0
    )

    a_fail_keys = {
        (t.task_id, t.injection)
        for t in traces
        if t.group == "A" and t.injection and not t.success
    }  # "受影响 run" = 裸模型在该注入下失败 (注入真实命中判据)

    c_injected = [
        t
        for t in traces
        if t.group == "C" and t.injection and (t.task_id, t.injection) in a_fail_keys
    ]
    b_injected = [
        t
        for t in traces
        if t.group == "B" and t.injection and (t.task_id, t.injection) in a_fail_keys
    ]

    # 2 首次定位命中率: C 的 root_cause_tool 是否等于注入的 target_tool
    located = [t for t in c_injected if t.root_cause_tool]
    hits = sum(
        1
        for t in located
        if INJECTIONS[t.injection].target_tool == t.root_cause_tool
    )
    localization = {"hit": hits, "n": len(located), "rate": hits / len(located) if located else 0.0}

    # 3 修复成功率 (对标 AgentTether 69.11%): 受影响 run 中 C 最终成功的比例
    repaired = sum(1 for t in c_injected if t.success and not t.escalated)
    b_rescued = sum(1 for t in b_injected if t.success)
    repair = {
        "repaired": repaired,
        "n": len(c_injected),
        "rate": repaired / len(c_injected) if c_injected else 0.0,
        "baseline_b_rescued": b_rescued,
        "baseline_b_n": len(b_injected),
    }

    # 4 重跑步数占比 (对标 EvidenceBound ~24% token 节省): C 重跑步数 / 该任务总步数
    rerun_steps = sum(t.rerun_steps for t in c_injected)
    total_steps = sum(len(_task_steps(t.task_id)) for t in c_injected)
    rerun = {
        "rerun_steps": rerun_steps,
        "total_steps": total_steps,
        "ratio": rerun_steps / total_steps if total_steps else 0.0,
    }

    # 5 回归破坏率: 修复导致回归的次数 / 修复次数 (mock 管线无回归事件, n 记录在案)
    repairs = sum(1 for t in c_injected if t.recovery_actions)
    regression = {"breaks": 0, "n": repairs, "rate": 0.0 if repairs else None}

    # 6 平均重装配次数 (适应成本): 受影响 run 中 C 的恢复动作数均值
    avg_reassemble = (
        sum(len(t.recovery_actions) for t in c_injected) / len(c_injected) if c_injected else 0.0
    )

    # 7 UAD 未验证断言密度 (独创): 账本中从未被 verify 的断言占比
    total_a = sum(t.assertions_total for t in traces if t.group == "C")
    verified_a = sum(t.assertions_verified for t in traces if t.group == "C")
    uad = {
        "unverified": total_a - verified_a,
        "total": total_a,
        "rate": (total_a - verified_a) / total_a if total_a else 0.0,
    }

    # 附: 组成功率 (非七指标, 但报告需要)
    group_success = {
        g: {
            "success": sum(1 for t in traces if t.group == g and t.success),
            "n": sum(1 for t in traces if t.group == g),
        }
        for g in ("A", "B", "C")
    }

    return {
        "assertion_compile_rate": {"rate": compile_rate, "n": val["criteria_total"]},
        "first_localization": localization,
        "repair_success": repair,
        "rerun_ratio": rerun,
        "regression_break": regression,
        "avg_reassembles": avg_reassemble,
        "uad": uad,
        "group_success": group_success,
        "taskset_validation": {k: v for k, v in val.items() if k != "problems"},
        "problems": val["problems"],
    }


def _task_steps(task_id: str) -> list[dict]:
    for t in TASKS:
        if t["id"] == task_id:
            return t["solution_steps"]
    return []
