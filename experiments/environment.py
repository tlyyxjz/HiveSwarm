"""SandboxEnv — 确定性本地工具环境 (实验的可执行世界).

7 个工具, 全部无网络、确定性强, 成功判据全部可机械判定 (6 原语).
injection_hook: (tool_name, call_index) → callable, 由 inject 模块挂入;
工具结果一律经 _deliver 出口, 注入器在出口处改写 (模拟"工具返回什么
agent 就拿到什么").

工具返回契约 (inspect 层的形状检查依据, C 组用它抓 shape 类注入):
  write_file/append_line → {"written": int}
  read_file → str; list_dir → list[str]; calc → int|float
  extract_number → float; text_search → list[int]
"""
from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from pathlib import Path

InjectionHook = Callable[[str, int, object], object]

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.USub: operator.neg,
}


class ToolError(Exception):
    """工具级异常 (超时/不可用类注入由此表达)."""


class ToolTimeout(ToolError):
    pass


def _safe_calc(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_calc(node.left), _safe_calc(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_calc(node.operand))
    raise ValueError(f"unsafe expression: {ast.dump(node)}")


class SandboxEnv:
    """在 root 目录里跑; call(tool, call_index, **kwargs) 是唯一入口."""

    TOOLS = (
        "write_file",
        "read_file",
        "append_line",
        "list_dir",
        "calc",
        "extract_number",
        "text_search",
    )

    def __init__(self, root: Path, injection_hook: InjectionHook | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._hook = injection_hook
        self.calls: list[dict] = []  # 执行轨迹: {tool, args, ok, preview}

    # ── 工具实现 (纯确定性) ─────────────────────────────────────────────

    def _t_write_file(self, path: str, content: str):
        (self.root / path).write_text(content, encoding="utf-8")
        return {"written": len(content)}

    def _t_read_file(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8")

    def _t_append_line(self, path: str, line: str):
        with (self.root / path).open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        return {"written": len(line) + 1}

    def _t_list_dir(self, pattern: str = "*") -> list:
        return sorted(p.name for p in self.root.glob(pattern))

    def _t_calc(self, expr: str):
        return _safe_calc(ast.parse(expr, mode="eval").body)

    def _t_extract_number(self, text: str, occurrence: int = 1) -> float:
        import re

        nums = re.findall(r"-?\d+(?:\.\d+)?", text)
        if len(nums) < occurrence:
            raise ToolError(f"no number at occurrence {occurrence} (found {len(nums)})")
        return float(nums[occurrence - 1])

    def _t_text_search(self, path: str, pattern: str) -> list:
        import re

        rx = re.compile(pattern)
        return [
            i + 1
            for i, line in enumerate((self.root / path).read_text(encoding="utf-8").splitlines())
            if rx.search(line)
        ]

    # ── 调度出口 (注入点) ────────────────────────────────────────────────

    def call(self, tool: str, call_index: int = 0, **kwargs):
        """call_index = 同一工具的第几次调用 (注入器按它决定是否命中)."""
        if tool not in self.TOOLS:
            raise ToolError(f"unknown tool {tool!r}")
        self.calls.append({"tool": tool, "args": kwargs, "call_index": call_index})
        try:
            result = getattr(self, f"_t_{tool}")(**kwargs)
        except ToolError as e:
            self.calls[-1].update(ok=False, error=str(e))
            raise
        if self._hook is not None:
            result = self._hook(tool, call_index, result)
        self.calls[-1].update(ok=True, preview=repr(result)[:60])
        return result

    # ── 判据评估 (可机械判定) ────────────────────────────────────────────

    def eval_criteria(self, criteria: list[dict]) -> list[dict]:
        """subject 只支持 'file:<相对路径>'. 用 6 原语评估, 返回逐条结果."""
        from layers.inspect.validator import (
            HasKeys,
            InRange,
            MaxLength,
            MinLength,
            NotEmpty,
            RegexMatch,
        )

        vmap = {
            "not_empty": lambda p: NotEmpty(),
            "min_length": lambda p: MinLength(p["n"]),
            "max_length": lambda p: MaxLength(p["n"]),
            "regex_match": lambda p: RegexMatch(p["pattern"]),
            "in_range": lambda p: InRange(p["low"], p["high"]),
            "has_keys": lambda p: HasKeys(tuple(p["keys"])),
        }
        out = []
        for c in criteria:
            subj = c["subject"]
            if not subj.startswith("file:"):
                raise ValueError(f"unsupported subject: {subj!r}")
            p = self.root / subj[5:]
            value = p.read_text(encoding="utf-8") if p.exists() else None
            res = vmap[c["validator_name"]](c.get("params", {})).check(value)
            out.append({"subject": subj, "ok": res.ok, "error": res.error})
        return out
