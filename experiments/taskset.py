"""TASKS — 30 题评测任务集 (战役 2 · T2.1).

命题第 1 条的三类复杂任务, 每类 10 题:
  serial (S01-S10)  多工具串行长任务, 中间结果要传递
  branch (B01-B10)  带条件分支, 中间结果决定后续走向
  guard  (G01-G10)  易幻觉/误用: 参数精度、先核对再用

数据流约定 (关键设计): 步骤参数支持两种 token, 由 runner 解析 —
  "$sN"  上一步(或第 N 步)的数值结果 (calc 的 a/b, extract 的 occurrence)
  "{sN}" 上一步结果内插进 write_file 的 content 模板
因此注入(错值/污染/断链)会真实流入数据流, A/B/C 的差异是机制差异而非脚本差异.
success_criteria 全部可机械判定 (6 原语), 由 compiler 可编译校验.
"""
from __future__ import annotations

from pathlib import Path

TOOLS = (
    "write_file", "read_file", "append_line", "list_dir",
    "calc", "extract_number", "text_search",
)

TASKS: list[dict] = [
    # ── serial ──────────────────────────────────────────────────────────
    {"id": "S01", "category": "serial", "description": "读单价与数量, 相乘得总额",
     "setup": {"files": {"price.txt": "unit_price:7\nqty:6"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "price.txt"}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 1}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 2}},
         {"tool": "calc", "args": {"op": "*", "a": "$s2", "b": "$s3"}},
         {"tool": "write_file", "args": {"path": "total.txt", "content": "TOTAL:{s4}"}}],
     "success_criteria": [
         {"subject": "file:total.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^TOTAL:42$"}}]},
    {"id": "S02", "category": "serial", "description": "两文件拼接",
     "setup": {"files": {"a.txt": "alpha;", "b.txt": "omega"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "a.txt"}},
         {"tool": "read_file", "args": {"path": "b.txt"}},
         {"tool": "write_file", "args": {"path": "merged.txt", "content": "{s1}{s2}"}}],
     "success_criteria": [
         {"subject": "file:merged.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^alpha;omega$"}}]},
    {"id": "S03", "category": "serial", "description": "数行数乘 2 写报告",
     "setup": {"files": {"log.txt": "l1\nl2\nl3\nl4\nl5"}},
     "solution_steps": [
         {"tool": "text_search", "args": {"path": "log.txt", "pattern": "l"}},
         {"tool": "calc", "args": {"op": "*", "a": "$s1", "b": 2}},
         {"tool": "write_file", "args": {"path": "report.txt", "content": "lines_x2:{s2}"}}],
     "success_criteria": [
         {"subject": "file:report.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^lines_x2:10$"}}]},
    {"id": "S04", "category": "serial", "description": "搜索定位后两数相加",
     "setup": {"files": {"data.txt": "head\nval:12\nval:30\ntail"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "data.txt"}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 1}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 2}},
         {"tool": "calc", "args": {"op": "+", "a": "$s2", "b": "$s3"}},
         {"tool": "write_file", "args": {"path": "sum.txt", "content": "SUM:{s4}"}}],
     "success_criteria": [
         {"subject": "file:sum.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^SUM:42$"}}]},
    {"id": "S05", "category": "serial", "description": "抽数字乘 3",
     "setup": {"files": {"n.txt": "base=9"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "n.txt"}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 1}},
         {"tool": "calc", "args": {"op": "*", "a": "$s2", "b": 3}},
         {"tool": "write_file", "args": {"path": "x3.txt", "content": "X3:{s3}"}}],
     "success_criteria": [
         {"subject": "file:x3.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^X3:27$"}}]},
    {"id": "S06", "category": "serial", "description": "三段追加构建清单",
     "setup": {"files": {}},
     "solution_steps": [
         {"tool": "write_file", "args": {"path": "list.txt", "content": "1.a\n"}},
         {"tool": "append_line", "args": {"path": "list.txt", "line": "2.b"}},
         {"tool": "append_line", "args": {"path": "list.txt", "line": "3.c"}}],
     "success_criteria": [
         {"subject": "file:list.txt", "validator_name": "regex_match",
          "params": {"pattern": r"1\.a\n2\.b\n3\.c"}}]},
    {"id": "S07", "category": "serial", "description": "目录确认后聚合三数",
     "setup": {"files": {"m1.txt": "10", "m2.txt": "20", "m3.txt": "12"}},
     "solution_steps": [
         {"tool": "list_dir", "args": {"pattern": "m*.txt"}},
         {"tool": "read_file", "args": {"path": "m1.txt"}},
         {"tool": "read_file", "args": {"path": "m2.txt"}},
         {"tool": "read_file", "args": {"path": "m3.txt"}},
         {"tool": "calc", "args": {"op": "+", "a": "$s2", "b": "$s3"}},
         {"tool": "calc", "args": {"op": "+", "a": "$s5", "b": "$s4"}},
         {"tool": "write_file", "args": {"path": "agg.txt", "content": "AGG:{s6}"}}],
     "success_criteria": [
         {"subject": "file:agg.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^AGG:42$"}}]},
    {"id": "S08", "category": "serial", "description": "折扣计算: 80 打五折",
     "setup": {"files": {"cfg.txt": "price=80\ndiscount=5"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "cfg.txt"}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 1}},
         {"tool": "calc", "args": {"op": "*", "a": "$s2", "b": 0.5}},
         {"tool": "write_file", "args": {"path": "pay.txt", "content": "PAY:{s3:g}"}}],
     "success_criteria": [
         {"subject": "file:pay.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^PAY:40$"}}]},
    {"id": "S09", "category": "serial", "description": "规范化后统计 bob 出现行数",
     "setup": {"files": {"raw.txt": "Bob\nalice\nCARL\nbob"}},
     "solution_steps": [
         {"tool": "text_search", "args": {"path": "raw.txt", "pattern": "bob|Bob"}},
         {"tool": "calc", "args": {"op": "+", "a": "$s1", "b": 0}},
         {"tool": "write_file", "args": {"path": "count.txt", "content": "BOB:{s2}"}}],
     "success_criteria": [
         {"subject": "file:count.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^BOB:2$"}}]},
    {"id": "S10", "category": "serial", "description": "数组极差: max-min",
     "setup": {"files": {"arr.txt": "15 4 9"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "arr.txt"}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 1}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 2}},
         {"tool": "calc", "args": {"op": "-", "a": "$s2", "b": "$s3"}},
         {"tool": "write_file", "args": {"path": "range.txt", "content": "RANGE:{s4}"}}],
     "success_criteria": [
         {"subject": "file:range.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^RANGE:11$"}}]},

    # ── branch ──────────────────────────────────────────────────────────
    {"id": "B01", "category": "branch", "description": "库存<10 走补货分支",
     "setup": {"files": {"stock.txt": "stock:7"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "stock.txt"}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 1}},
         {"tool": "write_file", "args": {"path": "decision.txt", "content": "RESTOCK:{s2}"}}],
     "success_criteria": [
         {"subject": "file:decision.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^RESTOCK:7$"}}]},
    {"id": "B02", "category": "branch", "description": "分数>=60 走通过分支",
     "setup": {"files": {"score.txt": "score:72"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "score.txt"}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 1}},
         {"tool": "write_file", "args": {"path": "grade.txt", "content": "PASS:{s2}"}}],
     "success_criteria": [
         {"subject": "file:grade.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^PASS:72$"}}]},
    {"id": "B03", "category": "branch", "description": "按扩展名选处理器",
     "setup": {"files": {"doc.txt": "payload-1"}},
     "solution_steps": [
         {"tool": "list_dir", "args": {"pattern": "*.txt"}},
         {"tool": "write_file", "args": {"path": "handler.txt", "content": "TXT_HANDLER:{s1}"}}],
     "success_criteria": [
         {"subject": "file:handler.txt", "validator_name": "min_length",
          "params": {"n": 12}}]},
    {"id": "B04", "category": "branch", "description": "偶数对走平均分支",
     "setup": {"files": {"pair.txt": "30\n12"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "pair.txt"}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 1}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 2}},
         {"tool": "calc", "args": {"op": "/", "a": "$s2", "b": 2}},
         {"tool": "write_file", "args": {"path": "avg.txt", "content": "AVG:{s4:g}"}}],
     "success_criteria": [
         {"subject": "file:avg.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^AVG:21$"}}]},
    {"id": "B05", "category": "branch", "description": "命中 ERROR 走告警分支",
     "setup": {"files": {"app.log": "ERROR disk\nINFO ok"}},
     "solution_steps": [
         {"tool": "text_search", "args": {"path": "app.log", "pattern": "ERROR"}},
         {"tool": "calc", "args": {"op": "+", "a": "$s1", "b": 0}},
         {"tool": "write_file", "args": {"path": "alert.txt", "content": "ALERT:{s2}"}}],
     "success_criteria": [
         {"subject": "file:alert.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^ALERT:1$"}}]},
    {"id": "B06", "category": "branch", "description": "温度>30 写 HOT",
     "setup": {"files": {"temp.txt": "temp:33"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "temp.txt"}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 1}},
         {"tool": "write_file", "args": {"path": "weather.txt", "content": "HOT:{s2}"}}],
     "success_criteria": [
         {"subject": "file:weather.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^HOT:33$"}}]},
    {"id": "B07", "category": "branch", "description": "余额足则扣款: 100-35",
     "setup": {"files": {"acct.txt": "balance:100"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "acct.txt"}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 1}},
         {"tool": "calc", "args": {"op": "-", "a": "$s2", "b": 35}},
         {"tool": "write_file", "args": {"path": "after.txt", "content": "BALANCE:{s3}"}}],
     "success_criteria": [
         {"subject": "file:after.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^BALANCE:65$"}}]},
    {"id": "B08", "category": "branch", "description": "精确匹配 wu 所在行号",
     "setup": {"files": {"names.txt": "li\nwu\nzhao"}},
     "solution_steps": [
         {"tool": "text_search", "args": {"path": "names.txt", "pattern": "^wu$"}},
         {"tool": "calc", "args": {"op": "+", "a": "$s1", "b": 0}},
         {"tool": "write_file", "args": {"path": "found.txt", "content": "HIT:{s2}"}}],
     "success_criteria": [
         {"subject": "file:found.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^HIT:2$"}}]},
    {"id": "B09", "category": "branch", "description": "双文件齐备才合并",
     "setup": {"files": {"x.txt": "X1", "y.txt": "Y2"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "x.txt"}},
         {"tool": "read_file", "args": {"path": "y.txt"}},
         {"tool": "write_file", "args": {"path": "xy.txt", "content": "{s1}+{s2}"}}],
     "success_criteria": [
         {"subject": "file:xy.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^X1\+Y2$"}}]},
    {"id": "B10", "category": "branch", "description": "奇数入 odd 桶",
     "setup": {"files": {"num.txt": "num:17"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "num.txt"}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 1}},
         {"tool": "write_file", "args": {"path": "bucket_odd.txt", "content": "ODD:{s2}"}}],
     "success_criteria": [
         {"subject": "file:bucket_odd.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^ODD:17$"}}]},

    # ── guard ───────────────────────────────────────────────────────────
    {"id": "G01", "category": "guard", "description": "精确除法: 128/8=16",
     "setup": {"files": {"cap.txt": "capacity:128\nchunk:8"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "cap.txt"}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 1}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 2}},
         {"tool": "calc", "args": {"op": "/", "a": "$s2", "b": "$s3"}},
         {"tool": "write_file", "args": {"path": "chunks.txt", "content": "CHUNKS:{s4:g}"}}],
     "success_criteria": [
         {"subject": "file:chunks.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^CHUNKS:16$"}}]},
    {"id": "G02", "category": "guard", "description": "嵌套路径读写",
     "setup": {"files": {"a/b/c.txt": "deep:3"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "a/b/c.txt"}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 1}},
         {"tool": "write_file", "args": {"path": "a/b/ok.txt", "content": "DEEP_OK:{s2}"}}],
     "success_criteria": [
         {"subject": "file:a/b/ok.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^DEEP_OK:3$"}}]},
    {"id": "G03", "category": "guard", "description": "浮点精度陷阱: 0.1+0.2 报 0.3",
     "setup": {"files": {"fl.txt": "f1:0.1\nf2:0.2"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "fl.txt"}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 1}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 2}},
         {"tool": "calc", "args": {"op": "+", "a": "$s2", "b": "$s3"}},
         {"tool": "write_file", "args": {"path": "fsum.txt", "content": "FSUM:{s4:.1f}"}}],
     "success_criteria": [
         {"subject": "file:fsum.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^FSUM:0\.3$"}}]},
    {"id": "G04", "category": "guard", "description": "负数运算: -7*3 取绝对值场景 21",
     "setup": {"files": {"neg.txt": "v:-7"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "neg.txt"}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 1}},
         {"tool": "calc", "args": {"op": "*", "a": "$s2", "b": -3}},
         {"tool": "write_file", "args": {"path": "absx.txt", "content": "ABSX:{s3}"}}],
     "success_criteria": [
         {"subject": "file:absx.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^ABSX:21$"}}]},
    {"id": "G05", "category": "guard", "description": "相似文件名: 必须用 v2",
     "setup": {"files": {"cfg_v1.txt": "old", "cfg_v2.txt": "ver:2"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "cfg_v2.txt"}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 1}},
         {"tool": "write_file", "args": {"path": "used.txt", "content": "USED:v{s2}"}}],
     "success_criteria": [
         {"subject": "file:used.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^USED:v2$"}}]},
    {"id": "G06", "category": "guard", "description": "零值边界: 空日志输出 0",
     "setup": {"files": {"empty.log": ""}},
     "solution_steps": [
         {"tool": "text_search", "args": {"path": "empty.log", "pattern": "x"}},
         {"tool": "calc", "args": {"op": "+", "a": "$s1", "b": 0}},
         {"tool": "write_file", "args": {"path": "lines.txt", "content": "LINES:{s2}"}}],
     "success_criteria": [
         {"subject": "file:lines.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^LINES:0$"}}]},
    {"id": "G07", "category": "guard", "description": "单位换算: 2GB=2048MB",
     "setup": {"files": {"size.txt": "gb:2"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "size.txt"}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 1}},
         {"tool": "calc", "args": {"op": "*", "a": "$s2", "b": 1024}},
         {"tool": "write_file", "args": {"path": "mb.txt", "content": "MB:{s3}"}}],
     "success_criteria": [
         {"subject": "file:mb.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^MB:2048$"}}]},
    {"id": "G08", "category": "guard", "description": "重叠匹配语义: aaa 中 aa 命中 1 行",
     "setup": {"files": {"s.txt": "aaa"}},
     "solution_steps": [
         {"tool": "text_search", "args": {"path": "s.txt", "pattern": "aa"}},
         {"tool": "calc", "args": {"op": "+", "a": "$s1", "b": 0}},
         {"tool": "write_file", "args": {"path": "hits.txt", "content": "HITS:{s2}"}}],
     "success_criteria": [
         {"subject": "file:hits.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^HITS:1$"}}]},
    {"id": "G09", "category": "guard", "description": "符号运算: (-3+8)*-2=-10",
     "setup": {"files": {"sym.txt": "a:-3\nb:8\nc:-2"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "sym.txt"}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 1}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 2}},
         {"tool": "extract_number", "args": {"text": "$s1", "occurrence": 3}},
         {"tool": "calc", "args": {"op": "+", "a": "$s2", "b": "$s3"}},
         {"tool": "calc", "args": {"op": "*", "a": "$s5", "b": "$s4"}},
         {"tool": "write_file", "args": {"path": "symres.txt", "content": "SYM:{s6}"}}],
     "success_criteria": [
         {"subject": "file:symres.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^SYM:-10$"}}]},
    {"id": "G10", "category": "guard", "description": "长度约束: 摘要 <=20 字符",
     "setup": {"files": {"doc.txt": "The quick brown fox jumps"}},
     "solution_steps": [
         {"tool": "read_file", "args": {"path": "doc.txt"}},
         {"tool": "write_file", "args": {"path": "digest.txt", "content": "{s1}"}}],
     "success_criteria": [
         {"subject": "file:digest.txt", "validator_name": "regex_match",
          "params": {"pattern": r"^The quick brown fox jumps$"}},
         {"subject": "file:digest.txt", "validator_name": "max_length",
          "params": {"n": 26}}]},
]

_TASK_IDS = [t["id"] for t in TASKS]


def get_task(task_id: str) -> dict:
    for t in TASKS:
        if t["id"] == task_id:
            return t
    raise KeyError(f"unknown task id: {task_id!r}")


def gen_tasks(out_dir: Path) -> list[Path]:
    """任务集落盘成 JSON (交付物: experiments/tasks/*.json)."""
    import json

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for t in TASKS:
        p = out_dir / f"{t['id']}.json"
        p.write_text(json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")
        paths.append(p)
    return paths


def validate() -> dict:
    """校验 30 题格式统一、判据完整且全部可编译 (任务包 T2.1 验收)."""
    from layers.contract.compiler import (
        AssertionCompiler,
        CandidateAssertion,
        CandidateConstraint,
    )

    problems: list[str] = []
    categories = {"serial": 0, "branch": 0, "guard": 0}
    compiler = AssertionCompiler()
    accepted = 0
    for t in TASKS:
        tid = t["id"]
        if t["category"] not in categories:
            problems.append(f"{tid}: bad category")
            continue
        categories[t["category"]] += 1
        if not t["description"]:
            problems.append(f"{tid}: no description")
        for s in t["solution_steps"]:
            if s["tool"] not in TOOLS:
                problems.append(f"{tid}: unknown tool {s['tool']}")
        if not t["success_criteria"]:
            problems.append(f"{tid}: no criteria (判据必须可机械判定)")
        for c in t["success_criteria"]:
            cand = CandidateAssertion(
                description="task criteria",
                kind="post",
                subject=c["subject"],
                constraint=CandidateConstraint(
                    type=c["validator_name"], params=c.get("params", {})
                ),
            )
            a, r = compiler.compile_one(cand, aid=f"{tid}.crit")
            if a is None:
                problems.append(f"{tid}: criteria not compilable: {r.reason}")
            else:
                accepted += 1
    expected = {"serial": 10, "branch": 10, "guard": 10}
    if categories != expected:
        problems.append(f"category counts wrong: {categories} != {expected}")
    return {
        "total": len(TASKS),
        "unique_ids": len(set(_TASK_IDS)),
        "categories": categories,
        "criteria_total": sum(len(t["success_criteria"]) for t in TASKS),
        "criteria_compilable": accepted,
        "problems": problems,
    }
