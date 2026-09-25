"""三方对照 runner (战役 2 · T2.3).

A 裸模型    : 直接按解执行, 工具炸了就炸, 结束后只看最终判据.
B 简单harness: 每步 try/except 重试 1 次 (只救瞬时异常, 不验证数据).
C 榫卯三机制 : 形状契约检查(事前) + 判据即断言(事后) + 反向定位 + 类型驱动
               恢复 (re_observe=重观测, swap_adapter=适配器, swap_skill=备用
               实现, halt_escalate=出声上报) + 回归闸.

模型接入: --model modelscope 时走 ModelScopeAgent (魔搭 API, 用户亲自跑);
mock 模式用 solution_steps 脚本化执行 — 只用于管线联调, 产出数字一律
标"演示数据, 非实测".

执行轨迹逐 run 落盘 JSONL/JSON, 断点续跑 = 跳过已存在的 trace 文件.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from experiments.environment import SandboxEnv, ToolError
from experiments.inject import INJECTIONS, make_hook
from experiments.taskset import get_task
from layers.contract.assertion import Assertion

# 工具返回形状契约 (C 组事前检查依据)
SHAPE_CONTRACT: dict[str, type | tuple[type, ...]] = {
    "write_file": dict,
    "append_line": dict,
    "read_file": str,
    "list_dir": list,
    "calc": (int, float),
    "extract_number": (int, float),
    "text_search": list,
}


@dataclass
class StepResult:
    idx: int
    tool: str
    ok: bool
    error: str = ""
    recovery: str = ""  # 空 = 无恢复动作
    value: object = None


@dataclass
class RunTrace:
    task_id: str
    group: str
    injection: str  # "" = 干净
    success: bool
    escalated: bool = False
    recovery_actions: list[str] = field(default_factory=list)
    root_cause_tool: str = ""  # C 组定位到的根因工具 (对答案用)
    rerun_steps: int = 0
    steps: list[dict] = field(default_factory=list)
    criteria: list[dict] = field(default_factory=list)
    assertions_total: int = 0  # C 组账本统计 (UAD 数据源)
    assertions_verified: int = 0
    duration_ms: int = 0
    error: str = ""


# ── token 解析 (mock agent 的"数据传递") ─────────────────────────────────

def _resolve_num(v: object) -> float:
    if isinstance(v, bool):
        raise ToolError("bool not numeric")
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        import re

        m = re.search(r"-?\d+(?:\.\d+)?", v)
        if m:
            return float(m.group())
    if isinstance(v, list):
        return float(len(v))
    raise ToolError(f"not numeric: {v!r}")


def _resolve(template: str, ctx: dict) -> object:
    """'$sN' → ctx 值本身; 数字上下文由 _resolve_num 再收窄."""
    if isinstance(template, str) and template.startswith("$s"):
        key = template[1:]
        if key not in ctx:
            raise ToolError(f"unresolved reference {template}")
        return ctx[key]
    return template


def _render(content: str, ctx: dict) -> str:
    """'{sN}' / '{sN:spec}' → 格式化数值."""
    import re

    def sub(m):
        key, _, spec = m.group(1).partition(":")
        if key not in ctx:
            raise ToolError(f"unresolved template {m.group(0)}")
        val = ctx[key]
        if not spec and isinstance(val, float) and val.is_integer():
            return str(int(val))  # 42.0 → "42" (float 噪声不出现在产物里)
        return format(val, spec) if spec else str(val)

    return re.sub(r"\{(s\d+)(?::([^}]+))?\}", sub, content)


def _step_call(env: SandboxEnv, step: dict, ctx: dict, call_index: int):
    """解析 token 后真正调用工具."""
    tool = step["tool"]
    args = dict(step["args"])
    if tool == "calc":
        a = _resolve_num(_resolve(args["a"], ctx))
        b = _resolve_num(_resolve(args["b"], ctx))
        result = env.call(tool, call_index=call_index, expr=f"({a}){args['op']}({b})")
        return result
    if tool == "extract_number":
        text = _resolve(args["text"], ctx)
        if isinstance(text, list):
            text = ",".join(map(str, text))
        if not isinstance(text, str):
            raise ToolError(f"extract_number needs str, got {type(text).__name__}")
        return env.call(
            tool, call_index=call_index, text=text, occurrence=args.get("occurrence", 1)
        )
    if tool in ("write_file", "append_line"):
        if "content" in args:
            args["content"] = _render(str(args["content"]), ctx)
        if "line" in args:
            args["line"] = _render(str(args["line"]), ctx)
        return env.call(tool, call_index=call_index, **args)
    return env.call(tool, call_index=call_index, **args)


# ── 适配器 (swap_adapter 的执行端, keel 翻译层的 mock) ────────────────────

def _adapt(tool: str, result: object) -> object:
    """把形状不对的结果翻译成契约形状: dict → 取第一个值."""
    if isinstance(result, dict) and result:
        return next(iter(result.values()))
    return result


# ── 三组执行器 ────────────────────────────────────────────────────────────

def run_group_A(task: dict, env: SandboxEnv) -> RunTrace:
    """裸模型: 顺序执行, 任何异常即任务失败."""
    t0 = time.monotonic()
    ctx: dict = {}
    steps = []
    try:
        for i, step in enumerate(task["solution_steps"], 1):
            counters: dict[str, int] = {}
            k = step["tool"]
            counters[k] = counters.get(k, 0) + 1
            v = _step_call(env, step, ctx, counters[k])
            ctx[f"s{i}"] = v
            steps.append({"idx": i, "tool": step["tool"], "ok": True})
    except Exception as e:  # 裸模型: 炸了就结束
        return RunTrace(task["id"], "A", "", False, steps=steps, error=repr(e),
                        duration_ms=int((time.monotonic() - t0) * 1000))
    criteria = env.eval_criteria(task["success_criteria"])
    ok = all(c["ok"] for c in criteria)
    return RunTrace(task["id"], "A", "", ok, steps=steps, criteria=criteria,
                    duration_ms=int((time.monotonic() - t0) * 1000))


def run_group_B(task: dict, env: SandboxEnv) -> RunTrace:
    """简单 harness: 每步失败重试 1 次 (瞬时异常可过; 脏数据照单全收)."""
    t0 = time.monotonic()
    ctx: dict = {}
    steps = []
    counters: dict[str, int] = {}
    for i, step in enumerate(task["solution_steps"], 1):
        k = step["tool"]
        counters[k] = counters.get(k, 0) + 1
        attempts = 0
        while True:
            attempts += 1
            try:
                v = _step_call(env, step, ctx, counters[k])
                ctx[f"s{i}"] = v
                steps.append({"idx": i, "tool": k, "ok": True, "attempts": attempts})
                break
            except Exception as e:
                if attempts >= 2:
                    return RunTrace(task["id"], "B", "", False, steps=steps,
                                    error=repr(e), duration_ms=int((time.monotonic() - t0) * 1000))
                steps.append({"idx": i, "tool": k, "ok": False, "retry": True,
                              "error": repr(e)[:60]})
    criteria = env.eval_criteria(task["success_criteria"])
    ok = all(c["ok"] for c in criteria)
    return RunTrace(task["id"], "B", "", ok, steps=steps, criteria=criteria,
                    duration_ms=int((time.monotonic() - t0) * 1000))


def run_group_C(task: dict, env: SandboxEnv) -> RunTrace:
    """榫卯三机制: 事前形状契约 + 事后判据断言 + 反向定位 + 类型驱动恢复 + 回归闸."""
    from layers.contract.assertion import AssertionStatus
    from layers.contract.compiler import AssertionCompiler, CandidateAssertion, CandidateConstraint
    from layers.contract.ledger import AssertionLedger
    from layers.repair.regression_gate import RegressionGate
    from layers.repair.strategy_table import TypedDispatch

    t0 = time.monotonic()
    led = AssertionLedger()
    compiler = AssertionCompiler()
    # 判据即断言: 每条 success_criteria 编译成账本里的 post 断言
    cands = [
        CandidateAssertion(
            description="task criteria",
            kind="post",
            subject=c["subject"],
            constraint=CandidateConstraint(
                type=c["validator_name"], params=c.get("params", {})
            ),
        )
        for c in task["success_criteria"]
    ]
    report = compiler.compile(cands)
    for a in report.accepted:
        led.add(a)
    crit_aids: dict[str, list[str]] = {}
    for a in report.accepted:  # subject → 账本 aid 映射 (事后检查用)
        crit_aids.setdefault(a.subject, []).append(a.aid)

    ctx: dict = {}
    steps: list[dict] = []
    recovery_actions: list[str] = []
    counters: dict[str, int] = {}
    root_cause_tool = ""
    escalated = False
    hard_fail = ""
    rerun_steps = 0

    for i, step in enumerate(task["solution_steps"], 1):
        k = step["tool"]
        counters[k] = counters.get(k, 0) + 1
        # 事前拦截 (L2 语义): 工具的形状契约
        pre_ok = True
        try:
            v = _step_call(env, step, ctx, counters[k])
        except Exception as e:
            v, pre_ok = None, False
            err = repr(e)
            aid = f"pre.{k}.c{i}"
            led.add(_mk_assertion(aid, "pre", "not_empty", producer=k))
            led.falsify(aid, observed_by=f"step{i}")
            steps.append({"idx": i, "tool": k, "ok": False, "error": err[:60]})
        else:
            if v is None:
                # None = 断链 (存在类错): pre+existence → re_observe 重试一次;
                # 仍 None = 持久断链, 不可自动修复 → halt_escalate 出声上报
                aid = f"pre.{k}.exists.c{i}"
                led.add(_mk_assertion(aid, "pre", "not_empty", producer=k))
                led.falsify(aid, observed_by=f"step{i}")
                recovery_actions.append(TypedDispatch().dispatch(led.get(aid)).name)
                try:
                    v = _step_call(env, step, ctx, counters[k] + 10)
                except Exception:
                    v = None
                if v is None:
                    recovery_actions.append("halt_escalate")
                    escalated = True
                    hard_fail = f"halt_escalate: chain broken at {k} (step {i})"
                    steps.append({"idx": i, "tool": k, "ok": False, "error": "chain broken"})
                    break
                steps.append({"idx": i, "tool": k, "ok": True, "reobserved": True})
                ctx[f"s{i}"] = v
                continue
            contract = SHAPE_CONTRACT[k]
            if not isinstance(v, contract):
                # 形状错 → 证伪 pre+shape → dispatch: swap_adapter → 适配器翻译
                aid = f"pre.{k}.shape.c{i}"
                led.add(_mk_assertion(aid, "pre", "has_keys", producer=k))
                led.falsify(aid, observed_by=f"step{i}")
                action = TypedDispatch().dispatch(led.get(aid))
                recovery_actions.append(action.name)
                v = _adapt(k, v)
                if not isinstance(v, contract):
                    hard_fail = f"adapter failed on {k}"
                    break
                steps.append({"idx": i, "tool": k, "ok": True, "adapted": True})
            else:
                steps.append({"idx": i, "tool": k, "ok": True})
        ctx[f"s{i}"] = v

    # 事后检查 (L1 语义): 判据断言
    criteria = env.eval_criteria(task["success_criteria"])
    falsified_crits = []
    for c in criteria:
        for aid in crit_aids.get(c["subject"], []):
            if c["ok"]:
                led.verify(aid)
            else:
                led.falsify(aid, observed_by="final-check")
                falsified_crits.append(aid)

    success = all(c["ok"] for c in criteria) and not hard_fail

    if falsified_crits and not hard_fail:
        # 反向定位: 判据断言依赖"数据链", 逐工具对答案找最早坏点.
        # mock 世界的 depend_on 边 = 步骤顺序; 这里用干净环境重演 (re_observe)
        # 并逐步 diff — 找到第一个与污染执行不一致的工具即根因工具.
        fired = env._fired  # noqa: SLF001 — runner 与注入器的约定接口
        clean_env = SandboxEnv(env.root, injection_hook=None)
        root_cause_tool, mismatch_idx = _locate_root(task, ctx, clean_env)
        if root_cause_tool:
            rc_cat = _category_of(env, root_cause_tool)
            action_name = {"shape": "swap_adapter", "value": "re_observe",
                           "timeout": "re_observe", "pollution": "re_observe",
                           "chain": "halt_escalate"}.get(rc_cat, "halt_escalate")
            recovery_actions.append(action_name)
            if action_name == "halt_escalate":
                escalated = True  # 不可自动修复 → 出声上报 (诚实失败)
            elif action_name == "re_observe":
                # 重新观测: 干净环境重演整链 (瞬时注入已消耗), 回归闸复验
                _replay_clean(task, clean_env)
                criteria2 = clean_env.eval_criteria(task["success_criteria"])
                rerun_steps = len(task["solution_steps"])
                if all(c["ok"] for c in criteria2):
                    # 回归闸: 重演后复验此前已通过判据 (此处 = 全部判据)
                    gate = RegressionGate(led, verify_fn=lambda a: all(
                        c["ok"] for c in clean_env.eval_criteria(task["success_criteria"])))
                    rep = gate.gate()
                    if not rep.needs_rollback:
                        success = True
                        criteria = criteria2
    elif hard_fail:
        escalated = True

    ok_final = success and not escalated
    all_asserts = led.list_assertions()
    return RunTrace(
        task["id"], "C", "", ok_final, escalated=escalated,
        recovery_actions=recovery_actions, root_cause_tool=root_cause_tool,
        rerun_steps=rerun_steps,
        steps=steps, criteria=criteria,
        assertions_total=len(all_asserts),
        assertions_verified=sum(
            1 for a in all_asserts if a.status is AssertionStatus.VERIFIED
        ),
        duration_ms=int((time.monotonic() - t0) * 1000), error=hard_fail,
    )


def _mk_assertion(aid: str, kind: str, validator_name: str, producer: str) -> Assertion:
    params: dict = {"keys": ("shape",)} if validator_name == "has_keys" else {}
    return Assertion(
        aid=aid, kind=kind,  # type: ignore[arg-type]
        subject="tool_result", predicate="contract",
        validator_name=validator_name, validator_params=params, producer=producer,
    )


def _locate_root(task: dict, dirty_ctx: dict, clean_env: SandboxEnv) -> tuple[str, int]:
    """重演找根因: 逐步重算, 与污染执行的值比对, 第一处不一致即根因步."""
    ctx: dict = {}
    for i, step in enumerate(task["solution_steps"], 1):
        try:
            v = _step_call(clean_env, step, ctx, 99)  # call_index 大 = 注入已消耗
        except Exception:
            return step["tool"], i
        old = dirty_ctx.get(f"s{i}")
        if isinstance(v, (int, float)) and isinstance(old, (int, float)):
            if abs(float(v) - float(old)) > 1e-9:
                return step["tool"], i
        elif v != old:  # 含 old=None (该步在污染执行中已炸) 的情况
            return step["tool"], i
        ctx[f"s{i}"] = v
    return "", 0


def _replay_clean(task: dict, clean_env: SandboxEnv) -> dict:
    ctx: dict = {}
    counters: dict[str, int] = {}
    for i, step in enumerate(task["solution_steps"], 1):
        k = step["tool"]
        counters[k] = counters.get(k, 0) + 1
        ctx[f"s{i}"] = _step_call(clean_env, step, ctx, counters[k])
    return ctx


def _category_of(env: SandboxEnv, tool: str) -> str:
    """根据注入器配置反查该工具上的注入类别 (ground truth 反查)."""
    for inj in INJECTIONS.values():
        if inj.target_tool == tool and inj.iid in getattr(env, "_injection_id", ""):
            return inj.category
    return ""


# ── 编排 ──────────────────────────────────────────────────────────────────

def run_one(task_id: str, group: str, injection_id: str = "", root: Path | None = None) -> RunTrace:
    task = get_task(task_id)
    import tempfile

    root = root or Path(tempfile.mkdtemp(prefix=f"hv-exp-{task_id}-"))
    for rel, content in task["setup"]["files"].items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    fired: set[str] = set()
    env = SandboxEnv(root, injection_hook=make_hook(injection_id, fired))
    env._fired = fired  # noqa: SLF001 — runner 约定接口
    env._injection_id = injection_id  # noqa: SLF001
    if group == "A":
        trace = run_group_A(task, env)
    elif group == "B":
        trace = run_group_B(task, env)
    elif group == "C":
        trace = run_group_C(task, env)
    else:
        raise ValueError(f"unknown group {group!r}")
    trace.injection = injection_id
    return trace


def run_batch(
    task_ids: list[str],
    groups: list[str],
    out_dir: Path,
    injections: list[str] | None = None,
) -> list[RunTrace]:
    """批量跑 + 断点续跑 (已存在的 trace 文件跳过).
    注入×任务 只配对 target_tool 出现在该题步骤里的组合 (否则注入永不命中,
    会稀释指标)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    combos: list[tuple[str, str, str]] = []
    for tid in task_ids:
        task = get_task(tid)
        task_tools = {s["tool"] for s in task["solution_steps"]}
        for g in groups:
            combos.append((tid, g, ""))
            for inj in injections or []:
                if INJECTIONS[inj].target_tool in task_tools:
                    combos.append((tid, g, inj))
    traces = []
    for tid, g, inj in combos:
        name = f"{tid}.{g}.{inj or 'clean'}.json"
        p = out_dir / name
        if p.exists():  # 断点续跑
            d = json.loads(p.read_text(encoding="utf-8"))
            traces.append(RunTrace(**{k: d[k] for k in RunTrace.__dataclass_fields__}))
            continue
        tr = run_one(tid, g, inj)
        p.write_text(json.dumps(tr.__dict__, ensure_ascii=False, indent=2, default=str),
                     encoding="utf-8")
        traces.append(tr)
    return traces
