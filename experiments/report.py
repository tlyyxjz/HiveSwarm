"""报告生成 (战役 2 · T2.4): markdown 报告, 可直接粘进对策书.

铁律: demo 数据源必须显著标注"演示数据, 非实测"; 真实数据源必须给
run 目录与模型标识. 对标列引用竞品公开数字, 我们的列只写实测/演示值.
"""
from __future__ import annotations

from pathlib import Path

from experiments.metrics import compute
from experiments.runner import RunTrace

_BANNER = (
    "> ⚠️ **演示数据，非实测** — 本报告由 mock 管线（脚本化解 + 确定性注入）生成，"
    "仅证明指标口径与报告格式可运行。真实数字必须来自魔搭 Qwen 的实跑"
    "（runner --model modelscope），届时本横幅消失并附 run 目录。"
)


def render(traces: list[RunTrace], *, demo: bool = True, run_dir: str = "") -> str:
    m = compute(traces)

    def pct(x):
        return f"{x * 100:.1f}%"

    lines: list[str] = []
    lines.append("# 榫卯三方对照实验报告\n")
    if demo:
        lines.append(_BANNER + "\n")
    lines.append(f"- run 目录: `{run_dir or '(未落盘)'}`")
    lines.append(f"- 模型标识: {'mock(脚本化解, 非模型)' if demo else 'modelscope:<见 run 配置>'}")
    lines.append(f"- 任务集: {m['taskset_validation']['total']} 题 "
                 f"(serial {m['taskset_validation']['categories']['serial']} / "
                 f"branch {m['taskset_validation']['categories']['branch']} / "
                 f"guard {m['taskset_validation']['categories']['guard']})\n")

    lines.append("## 组成功率\n")
    lines.append("| 组 | 配置 | 成功/总数 |")
    lines.append("|---|---|---|")
    desc = {"A": "裸模型直接执行", "B": "简单 harness(重试1次)", "C": "榫卯三机制"}
    for g in ("A", "B", "C"):
        s = m["group_success"][g]
        lines.append(f"| {g} | {desc[g]} | {s['success']}/{s['n']} |")

    lines.append("\n## 七指标\n")
    lines.append("| # | 指标 | 本实验值 | 分母 n | 对标基线 |")
    lines.append("|---|---|---|---|---|")
    r = m
    lines.append(
        f"| 1 | 断言可编译率 | {pct(r['assertion_compile_rate']['rate'])} "
        f"| {r['assertion_compile_rate']['n']} | 无 (自证未被语言污染) |"
    )
    lines.append(
        f"| 2 | 首次定位命中率 | {pct(r['first_localization']['rate'])} "
        f"| {r['first_localization']['n']} | LongRCA 24.1% (范式不同: 我们是确定性图搜索) |"
    )
    lines.append(
        f"| 3 | 修复成功率 | {pct(r['repair_success']['rate'])} "
        f"| {r['repair_success']['n']} | AgentTether 69.11% |"
    )
    lines.append(
        f"| 4 | 重跑步数占比 | {pct(r['rerun_ratio']['ratio'])} "
        f"| {r['rerun_ratio']['total_steps']} | EvidenceBound ~24% token 节省 |"
    )
    rb = r["regression_break"]
    lines.append(
        f"| 5 | 回归破坏率 | {pct(rb['rate']) if rb['rate'] is not None else 'n/a'} "
        f"| {rb['n']} | HarnessFix regression-free 要求 |"
    )
    lines.append(
        f"| 6 | 平均重装配次数 | {r['avg_reassembles']:.2f} "
        f"| {r['repair_success']['n']} | 无前例 |"
    )
    lines.append(
        f"| 7 | UAD 未验证断言密度 | {pct(r['uad']['rate'])} "
        f"| {r['uad']['total']} | 无前例 (独创) |"
    )

    lines.append("\n### 口径说明\n")
    lines.append("- 受影响 run 的定义: 同一 (题, 注入) 组合下 A 组失败 —— 即注入真实命中判据；")
    lines.append("- 指标 3/4/6 只在受影响 run 上统计，避免\"注入根本没生效\"稀释数字；")
    lines.append("- 指标 5 在 mock 管线下无回归事件（n=0 时记 n/a，不冒充实测）；")
    lines.append("- 指标 7 的 UAD 在 mock 管线下偏乐观：判据全部被执行验证；"
                 "真实实验中由模型生成的候选断言才可能出现从未验证的项。\n")

    lines.append("## 已知限制\n")
    lines.append("- mock 模式的\"模型\"是脚本化解，不代表模型能力，只代表机制差异；")
    lines.append("- B 组的简单 harness 只会盲目重试，不代表 dsh 的完整能力；")
    lines.append("- chain 类(持久断链)不可自动修复，C 组诚实上报 halt_escalate，计为失败。\n")
    return "\n".join(lines) + "\n"


def write_report(traces: list[RunTrace], out: Path, *, demo: bool = True, run_dir: str = "") -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(traces, demo=demo, run_dir=run_dir), encoding="utf-8")
    return out
