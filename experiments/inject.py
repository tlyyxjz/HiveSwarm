"""失败注入器 (战役 2 · T2.2): 5 类 × 5 例 = 25 个注入点, 每点独立开关.

注入语义 (决定 A/B/C 谁能扛住):
  shape     持久  工具返回格式错 (C 用形状契约+适配器修复; A/B 拿坏数据)
  value     单次  返回值错但格式合法 (静默污染; C 重观测可恢复)
  timeout   单次  抛 ToolTimeout (B/C 重试可恢复; 裸 A 直接炸)
  pollution 单次  中间产出被悄悄污染 (C 根因定位后重跑可恢复)
  chain     持久  断链: 工具返回空/None (不可自动修复, C 诚实 halt_escalate)

ground truth: 每个注入点声明 target_tool, 供"首次定位命中率"指标对答案
(C 的 root_cause 是否指到被注入的工具).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from experiments.environment import ToolTimeout

Hook = Callable[[str, int, object], object]
CATEGORIES = ("shape", "value", "timeout", "pollution", "chain")
ONCE_CATEGORIES = ("value", "timeout", "pollution")


@dataclass(frozen=True)
class Injection:
    iid: str  # 如 shape.1
    category: str
    target_tool: str
    description: str
    hook: Hook


# ── hook 实现 (全部确定性) ───────────────────────────────────────────────

def _shape_wrap(tool: str, idx: int, result: object) -> object:
    """用 dict 冒充原类型 (形状错)."""
    if isinstance(result, str):
        return {"content": result}
    if isinstance(result, list):
        return {"items": result}
    return {"value": result}


def _value_shift(tool: str, idx: int, result: object) -> object:
    """值错但类型合法 (静默)."""
    if isinstance(result, (int, float)) and not isinstance(result, bool):
        return result + 1
    return result


def _value_half(tool: str, idx: int, result: object) -> object:
    if isinstance(result, (int, float)) and not isinstance(result, bool):
        return result + 0.5
    return result


def _timeout(tool: str, idx: int, result: object) -> object:
    raise ToolTimeout(f"injected timeout on {tool}#{idx}")


def _chain_empty(tool: str, idx: int, result: object) -> object:
    if isinstance(result, str):
        return ""
    if isinstance(result, list):
        return []
    return None


def _value_bump_search(tool: str, idx: int, result: object) -> object:
    if isinstance(result, list):
        return [x + 1 for x in result if isinstance(x, int)]
    return result


def _value_ghost(tool: str, idx: int, result: object) -> object:
    if isinstance(result, list):
        return list(result) + ["ghost.tmp"]
    return result


def _pollute_calc_x2(tool: str, idx: int, result: object) -> object:
    if isinstance(result, (int, float)) and not isinstance(result, bool):
        return result * 2
    return result


def _pollute_read_drop(tool: str, idx: int, result: object) -> object:
    if isinstance(result, str) and "\n" in result:
        return "\n".join(result.splitlines()[:-1]) + "\n"
    return result


def _pollute_extract_x10(tool: str, idx: int, result: object) -> object:
    if isinstance(result, (int, float)) and not isinstance(result, bool):
        return result * 10
    return result


def _pollute_read_num(tool: str, idx: int, result: object) -> object:
    """读文件结果里第一个数字 +100 (静默) — 下游抽取即错."""
    import re

    if isinstance(result, str):
        m = re.search(r"-?\d+(?:\.\d+)?", result)
        if m:
            num = float(m.group()) + 100
            new = str(int(num)) if num == int(num) else str(num)
            return result[: m.start()] + new + result[m.end() :]
    return result


_SPECS = [
    # ── shape ×5 (持久) ────────────────────────────────────────────────
    ("shape.1", "shape", "read_file", "读文件返回 dict 冒充 str", _shape_wrap),
    ("shape.2", "shape", "list_dir", "列目录返回 dict 冒充 list", _shape_wrap),
    ("shape.3", "shape", "calc", "计算结果包 dict", _shape_wrap),
    ("shape.4", "shape", "text_search", "搜索结果包 dict", _shape_wrap),
    ("shape.5", "shape", "extract_number", "抽数字返回 dict", _shape_wrap),
    # ── value ×5 (单次, 格式合法) ──────────────────────────────────────
    ("value.1", "value", "calc", "计算值 +1 (静默)", _value_shift),
    ("value.2", "value", "extract_number", "抽取值 +0.5 (静默)", _value_half),
    ("value.3", "value", "calc", "计算值 +1 (静默, 备用靶)", _value_shift),
    ("value.4", "value", "text_search", "行号整体 +1 (静默)", _value_bump_search),
    ("value.5", "value", "list_dir", "列表尾加 ghost.tmp (静默)", _value_ghost),
    # ── timeout ×5 (单次, 重试可过) ────────────────────────────────────
    ("timeout.1", "timeout", "read_file", "首次调用超时", _timeout),
    ("timeout.2", "timeout", "calc", "首次调用超时", _timeout),
    ("timeout.3", "timeout", "list_dir", "首次调用超时", _timeout),
    ("timeout.4", "timeout", "text_search", "首次调用超时", _timeout),
    ("timeout.5", "timeout", "write_file", "首次调用超时", _timeout),
    # ── pollution ×5 (单次, 静默改中间量) ──────────────────────────────
    ("pollution.1", "pollution", "calc", "中间计算 ×2 (静默)", _pollute_calc_x2),
    ("pollution.2", "pollution", "calc", "中间计算 ×2 (静默, 备用靶)", _pollute_calc_x2),
    ("pollution.3", "pollution", "read_file", "返回前丢最后一行 (静默)", _pollute_read_drop),
    ("pollution.4", "pollution", "extract_number", "抽取值 ×10 (静默)", _pollute_extract_x10),
    ("pollution.5", "pollution", "read_file", "内容首个数字 +100 (静默)", _pollute_read_num),
    # ── chain ×5 (持久断链) ────────────────────────────────────────────
    ("chain.1", "chain", "read_file", "读文件永远空串", _chain_empty),
    ("chain.2", "chain", "list_dir", "列目录永远空列表", _chain_empty),
    ("chain.3", "chain", "calc", "计算永远 None", _chain_empty),
    ("chain.4", "chain", "text_search", "搜索永远空列表", _chain_empty),
    ("chain.5", "chain", "extract_number", "抽数字永远 None", _chain_empty),
]

INJECTIONS: dict[str, Injection] = {
    iid: Injection(iid=iid, category=cat, target_tool=tool, description=desc, hook=fn)
    for iid, cat, tool, desc, fn in _SPECS
}


def by_category() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {c: [] for c in CATEGORIES}
    for iid, inj in INJECTIONS.items():
        out[inj.category].append(iid)
    return out


def make_hook(injection_id: str, fired: set[str]) -> Hook | None:
    """把注入点装成 SandboxEnv 的 injection_hook. fired 记录已触发键;
    单次类(value/timeout/pollution)只打一发 — 第二次调用是干净的
    (C 组的重观测因此能恢复; 这对应"瞬时污染"的真实语义)."""
    inj = INJECTIONS.get(injection_id)
    if inj is None:
        return None

    def hook(tool: str, idx: int, result: object) -> object:
        if tool != inj.target_tool:
            return result
        if inj.category in ONCE_CATEGORIES:
            if injection_id in fired:
                return result
            fired.add(injection_id)
        return inj.hook(tool, idx, result)

    return hook
