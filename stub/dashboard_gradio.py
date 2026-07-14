"""GradioDashboard v2 — 战情看板 (Day 9 UI 升级).

变更（v2 vs v1，按 ROI 排序）:
- P0 #10  Tab 默认顺序: Health→Submit→Tasks→Events→Skills
- P0 #6   Submit 加 gr.Progress 回调绑 subtasks 进度
- P0 #8   Error 分类 (Network/Parameter/System) + 可执行提示
- P0 #7   顶部 StatusBar 全局可见 (skill 数/活跃 borrow/失败数/最近事件)
- P1 #1   5 Tab Timer 自动刷新 (2s, Submit 除外)
- P1 #2   Skills/Tasks 改 gr.Dataframe (可排序)
- P1 #3   暗色主题 Monochrome + custom_css (OKLCH + Geist/JetBrains Mono)
- 额外:  Light/Dark theme toggle

设计纪律来源:
- design-god skill (字体/AI Slop 防火墙)
- impeccable (OKLCH/对比度/卡片 12-16px 圆角/单边 border ≤1px 禁令)
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from datetime import datetime
from typing import Any

import gradio as gr

from core.events import EventType
from core.brain import Plan, SubTask


# ── 配色 + 字体（OKLCH 调色，custom_css 注入）───────────────────
# 设计纪律: 不准 Inter/Roboto/Arial, 不准紫蓝渐变, 单 accent, tinted neutrals
CUSTOM_CSS = """
:root {
  --bg-base: #F8FAFC;
  --bg-card: #FFFFFF;
  --bg-hover: #F1F5F9;
  --text-primary: #0F172A;
  --text-muted: #475569;
  --text-subtle: #94A3B8;
  --accent: #0891B2;
  --accent-dim: #06B6D4;
  --success: #059669;
  --warning: #D97706;
  --danger: #DC2626;
  --border: #E2E8F0;
  --shadow: 0 1px 3px rgba(15,23,42,0.08), 0 1px 2px rgba(15,23,42,0.04);
}
.gradio-container {
  background: var(--bg-base) !important;
  color: var(--text-primary) !important;
  font-family: 'Geist', 'JetBrains Mono', -apple-system, BlinkMacSystemFont, sans-serif !important;
  font-feature-settings: 'cv11', 'ss01';
}
.gradio-container h1, .gradio-container h2, .gradio-container h3 {
  letter-spacing: -0.02em;
  font-weight: 600;
}
.tab-nav button {
  font-family: 'Geist', sans-serif !important;
  letter-spacing: -0.01em;
  font-weight: 500;
}
.status-bar {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 18px;
  margin-bottom: 14px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
  box-shadow: var(--shadow);
}
.status-pill {
  display: inline-flex;
  align-items: center;
  padding: 5px 12px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  background: var(--bg-hover);
  color: var(--text-primary);
  border: 1px solid var(--border);
  transition: all 120ms ease;
}
.status-pill .label { color: var(--text-muted); margin-right: 6px; font-weight: 400; }
.status-pill.ok { border-left: 2px solid var(--success); }
.status-pill.warn { border-left: 2px solid var(--warning); }
.status-pill.danger { border-left: 2px solid var(--danger); }
.error-net { color: var(--danger); border-left: 3px solid var(--danger); padding: 10px 14px; background: rgba(239,68,68,0.06); border-radius: 4px; }
.error-param { color: var(--warning); border-left: 3px solid var(--warning); padding: 10px 14px; background: rgba(245,158,11,0.06); border-radius: 4px; }
.error-system { color: var(--text-muted); border-left: 3px solid var(--text-subtle); padding: 10px 14px; background: var(--bg-hover); border-radius: 4px; }
.dataframe { font-family: 'JetBrains Mono', 'Geist Mono', monospace !important; font-size: 13px !important; }
@keyframes pulse-ok { 0%, 100% { box-shadow: 0 0 0 0 rgba(5,150,105,0.35); } 50% { box-shadow: 0 0 0 6px rgba(5,150,105,0); } }
@keyframes pulse-warn { 0%, 100% { box-shadow: 0 0 0 0 rgba(217,119,6,0.35); } 50% { box-shadow: 0 0 0 6px rgba(217,119,6,0); } }
@keyframes pulse-fail { 0%, 100% { box-shadow: 0 0 0 0 rgba(220,38,38,0.4); } 50% { box-shadow: 0 0 0 6px rgba(220,38,38,0); } }
@keyframes fade-in { from { opacity: 0; transform: translateY(2px); } to { opacity: 1; transform: translateY(0); } }
.tabitem { animation: fade-in 240ms ease-out; }
.status-pill.ok { animation: pulse-ok 2.4s ease-in-out infinite; }
.status-pill.warn { animation: pulse-warn 1.8s ease-in-out infinite; }
.status-pill.danger { animation: pulse-fail 1.2s ease-in-out infinite; }
.gradio-container button { font-weight: 600 !important; min-height: 38px !important; border-radius: 8px !important; transition: all 150ms ease !important; }
.gradio-container button:not([disabled]):hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(8,145,178,0.25); background: var(--accent) !important; color: #fff !important; }
.gradio-container button.primary { background: var(--accent) !important; color: #fff !important; }
.gradio-container button.primary:hover { background: #0E7490 !important; }
"""


# ── Headers for Dataframes ──────────────────────────────────────
SKILLS_HEADERS = ["Skill", "API", "Refcount", "Success", "Failure", "Error Rate"]
TASKS_HEADERS = ["Time", "Type", "Details"]


class GradioDashboard:
    """Gradio 战情看板 v2. 5 面板 + 顶部 StatusBar + 暗色主题."""

    def __init__(
        self,
        pool=None,
        bus=None,
        brain=None,
        memory=None,
        port: int = 7860,
        log_path: str = "~/.hiveswarm/logs/events.jsonl",
        reports_dir: str = "~/.hiveswarm/reports",
        theme: str = "light",
    ) -> None:
        self.port = port
        self._pool = pool
        self._bus = bus
        self._brain = brain
        self._memory = memory
        self._theme_mode = theme
        self._log_path = Path(log_path).expanduser()
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._reports_dir = Path(reports_dir).expanduser()
        self._reports_dir.mkdir(parents=True, exist_ok=True)

    # ── StatusBar ──────────────────────────────────────────────
    def _render_statusbar(self) -> str:
        """顶部全局状态条: skill 数 / 活跃 borrow / 失败数 / 最近事件时间."""
        if self._pool is None:
            return '<div class="status-bar"><span class="status-pill danger"><span class="label">Pool</span>not connected</span></div>'

        names = self._pool.list_available()
        health = self._pool.health_report()
        total_borrow = sum(h.get("refcount", 0) for h in health.values())
        total_fail = sum(h.get("health", {}).get("failure", 0) for h in health.values())
        total_success = sum(h.get("health", {}).get("success", 0) for h in health.values())
        success_rate = (
            total_success / (total_success + total_fail)
            if (total_success + total_fail) > 0
            else 1.0
        )

        last_event_ts = "—"
        if self._bus is not None:
            evts = self._bus.recent(1)
            if evts:
                last_event_ts = evts[-1].get("ts", "—")[:19]

        if total_fail == 0:
            status_cls = "ok"
            status_text = "OK"
        elif total_fail < 5:
            status_cls = "warn"
            status_text = "WARN"
        else:
            status_cls = "danger"
            status_text = "DEGRADED"

        return (
            '<div class="status-bar">'
            f'<span class="status-pill"><span class="label">Status</span>{status_text}</span>'
            f'<span class="status-pill"><span class="label">Skills</span>{len(names)}</span>'
            f'<span class="status-pill"><span class="label">Borrows</span>{total_borrow}</span>'
            f'<span class="status-pill {status_cls}"><span class="label">Success Rate</span>{success_rate:.1%}</span>'
            f'<span class="status-pill {status_cls}"><span class="label">Failures</span>{total_fail}</span>'
            f'<span class="status-pill"><span class="label">Last Event</span>{last_event_ts}</span>'
            "</div>"
        )

    # ── Panel 1: Skills (Dataframe) ────────────────────────────
    def _render_skills(self) -> list[list[Any]]:
        """技能面板: Dataframe 格式 [[row1], [row2], ...]."""
        if self._pool is None:
            return [["error", "Pool not connected", 0, 0, 0, "0.0%"]]
        health = self._pool.health_report()
        names = self._pool.list_available()
        if not names:
            return [["—", "—", 0, 0, 0, "0.0%"]]
        rows = []
        for name in names:
            m = self._pool.get_manifest(name)
            h = health.get(name, {})
            hh = h.get("health", {})
            rows.append([
                name,
                m.get("api_version", "?") if m else "?",
                h.get("refcount", 0),
                hh.get("success", 0),
                hh.get("failure", 0),
                f"{hh.get('error_rate', 0):.1%}",
            ])
        return rows

    # ── Panel 2: Tasks (Dataframe) ────────────────────────────
    def _render_tasks(self, n: int = 30) -> list[list[Any]]:
        """任务面板: Dataframe."""
        if self._bus is None:
            return [["error", "—", "Bus not connected"]]
        events = self._bus.recent(n * 3)
        task_events = [
            e for e in events
            if e["type"] in (
                EventType.TASK_STARTED.value,
                EventType.TASK_COMPLETED.value,
                EventType.TASK_FAILED.value,
            )
        ]
        if not task_events:
            return [["—", "—", "No task events yet"]]
        rows = []
        for e in task_events[-n:]:
            ts = e.get("ts", "")[:19]
            etype = e["type"].split(".")[-1]  # 去掉 "EventType." 前缀
            details = json.dumps(e, ensure_ascii=False)[:120]
            rows.append([ts, etype, details])
        return rows

    # ── Panel 3: Events (Markdown) ────────────────────────────
    def _render_events(self, n: int = 30) -> str:
        """事件面板: Markdown 文本流."""
        if self._bus is None:
            return "Bus not connected"
        events = self._bus.recent(n)
        if not events:
            return "No events yet"
        lines = []
        for e in events:
            ts = e.get("ts", "")[:19]
            etype = e.get("type", "?").split(".")[-1]
            lines.append(f"`{ts}` **{etype}**")
        return "\n\n".join(lines)

    # ── Panel 6: Brain（任务计划与拆解）─────────────────────────
    def _render_brain(self, n: int = 30) -> list[list[Any]]:
        """大脑面板: 任务计划 / subtask 拆解 + 状态 + 技能 + 耗时."""
        if self._bus is None:
            return [["error", "—", "—", "—", "—", "—", "—"]]
        events = self._bus.recent(300)
        plan_events = [e for e in events if e.get("type") == EventType.TASK_STARTED.value]
        if not plan_events:
            return [["—", "—", "—", "—", "—", "No plan events yet", "—"]]

        # 索引每个 task 的 subtask 技能 + 状态
        task_subtask_skills: dict[str, set[str]] = {}
        task_status: dict[str, str] = {}
        for e in events:
            tid = e.get("task_id")
            if not tid:
                continue
            if e.get("type") == EventType.TASK_COMPLETED.value:
                task_status[tid] = "PASS"
            elif e.get("type") == EventType.TASK_FAILED.value:
                task_status.setdefault(tid, "FAIL")

        rows = []
        for e in plan_events[-n:]:
            ts = e.get("ts", "")[:19]
            task_id = e.get("task_id", "—")
            rationale = (e.get("rationale", "—") or "—")[:50]
            subtasks = e.get("subtasks", [])
            n_sub = len(subtasks) if isinstance(subtasks, (list, tuple)) else 0
            # 拉技能（从 checked_out 关联）
            skills_str = ", ".join(sorted(task_subtask_skills.get(task_id, set()))[:3]) or "—"
            status = task_status.get(task_id, "PENDING")
            # 简单 duration：如果有 completed/failed 事件就比对
            dur = "—"
            for fe in events:
                if fe.get("task_id") == task_id and fe.get("type") in (
                    EventType.TASK_COMPLETED.value, EventType.TASK_FAILED.value
                ):
                    try:
                        from datetime import datetime
                        t0 = datetime.fromisoformat(e.get("ts", ""))
                        t1 = datetime.fromisoformat(fe.get("ts", ""))
                        dur = f"{(t1-t0).total_seconds():.1f}s"
                    except Exception:  # noqa: BLE001
                        dur = "?"
                    break
            rows.append([ts, task_id, n_sub, status, dur, rationale, skills_str])
        return rows

    # ── Panel 7: Repair（修复历史）──────────────────────────
    def _render_repair(self, n: int = 30) -> str:
        """修复面板: 失败事件 + Repair 触发 + action + 目标 skill."""
        if self._bus is None:
            return "Bus not connected"
        events = self._bus.recent(300)
        fail_evts = [e for e in events if e.get("type") == EventType.TASK_FAILED.value]
        repair_evts = [e for e in events if e.get("type") == EventType.REPAIR_TRIGGERED.value]

        if not fail_evts and not repair_evts:
            return "## 无失败事件 OK"

        # 配对：每个 FAILED 找最近的 TRIGGERED
        lines = ["## 修复历史\n"]
        pairs = []
        for f in fail_evts:
            # 找最近的 repair
            triggered = None
            for r in repair_evts:
                if r.get("task_id") == f.get("task_id"):
                    triggered = r
                    break
            pairs.append((f, triggered))
        pairs.sort(key=lambda p: p[0].get("ts", ""), reverse=True)

        for f, r in pairs[:n]:
            ts = f.get("ts", "")[:19]
            sub_id = f.get("subtask_id") or f.get("task_id", "—")
            error = (f.get("error", "") or "")[:60]
            lines.append(f"`{ts}` **[FAIL]** `{sub_id}`")
            lines.append(f"  └ 原因: {error}")
            if r:
                action = r.get("action", "—")
                target = r.get("target_skill") or r.get("subtask_id") or "—"
                rts = r.get("ts", "")[:19]
                lines.append(f"  └ 修复: **{action}** → `{target}` @ `{rts}`")
            else:
                lines.append(f"  └ 修复: (无)")
            lines.append("")

        # 按 action 统计
        action_stats: dict[str, int] = {}
        for _, r in pairs:
            if r:
                a = r.get("action", "?")
                action_stats[a] = action_stats.get(a, 0) + 1
        stats_str = " · ".join(f"{k}={v}" for k, v in action_stats.items()) or "—"
        lines.append(f"---\n**Failures**: {len(fail_evts)} · **Repairs**: {len(repair_evts)}")
        lines.append(f"\n**Actions**: {stats_str}")
        return "\n".join(lines)

    # ── Panel 8: Memory（记忆层）────────────────────────────
    def _render_memory(self) -> str:
        """记忆面板: 按 tier 分桶 + 总数 + 抽样值."""
        if self._memory is None:
            return "**Memory not connected**"

        try:
            from layers.memory.store import MemoryTier
            tier_rows = []
            total = 0
            for tier in MemoryTier:
                try:
                    keys = self._memory.list(tier)
                    count = len(keys)
                    total += count
                    sample_keys = ", ".join(keys[:3]) if keys else "—"
                    # 抽一个 value 看一眼
                    sample_val = "—"
                    if keys:
                        v = self._memory.get(tier, keys[0])
                        if isinstance(v, dict):
                            sample_val = "{" + ", ".join(f"{k}=..." for k in list(v.keys())[:3]) + "}"
                        else:
                            sample_val = str(v)[:60]
                    tier_rows.append((tier.value, count, sample_keys, sample_val))
                except Exception as exc:  # noqa: BLE001
                    tier_rows.append((tier.value, "?", "—", str(exc)[:40]))

            md = "## 记忆层 · Memory Tiers\n\n"
            md += "| Tier | Keys | Sample Keys | Sample Value |\n|---|---|---|---|\n"
            for tier, cnt, keys_s, val_s in tier_rows:
                md += f"| **{tier}** | {cnt} | `{keys_s}` | `{val_s}` |\n"
            md += f"\n**Total**: {total} keys across {len(tier_rows)} tiers"
            return md
        except Exception as exc:  # noqa: BLE001
            return f"**Memory error**: {exc}"

    # ── Panel 9: Inspect（检查报告）────────────────────────
    def _render_inspect(self, n: int = 30) -> list[list[Any]]:
        """检查面板: 每个 task 的成功/失败计数 + 判定 + 耗时."""
        if self._bus is None:
            return [["error", "—", "—", 0, 0, "—", "—"]]
        events = self._bus.recent(500)
        by_task: dict[str, dict[str, Any]] = {}
        for e in events:
            tid = e.get("task_id", "—")
            if e.get("type") == EventType.TASK_STARTED.value:
                by_task.setdefault(tid, {"ok": 0, "fail": 0, "ts_start": e.get("ts", ""), "ts_end": ""})
            if e.get("type") in (EventType.TASK_COMPLETED.value, EventType.TASK_FAILED.value):
                bucket = by_task.setdefault(tid, {"ok": 0, "fail": 0, "ts_start": "", "ts_end": ""})
                if e["type"] == EventType.TASK_COMPLETED.value:
                    bucket["ok"] += 1
                else:
                    bucket["fail"] += 1
                bucket["ts_end"] = e.get("ts", bucket["ts_end"])
                bucket["ts"] = e.get("ts", "")

        if not by_task:
            return [["—", "—", "—", 0, 0, "—", "No inspect data yet"]]

        rows = []
        for tid, b in sorted(by_task.items(), key=lambda kv: kv[1].get("ts", ""), reverse=True)[:n]:
            total = b["ok"] + b["fail"]
            rate = f"{b['ok']/total:.1%}" if total else "—"
            verdict = "PASS" if b["fail"] == 0 else ("WARN" if b["fail"] < b["ok"] else "FAIL")
            ts = b.get("ts", "")[:19]
            # duration
            dur = "—"
            if b.get("ts_start") and b.get("ts_end"):
                try:
                    from datetime import datetime
                    t0 = datetime.fromisoformat(b["ts_start"])
                    t1 = datetime.fromisoformat(b["ts_end"])
                    dur = f"{(t1-t0).total_seconds():.1f}s"
                except Exception:  # noqa: BLE001
                    dur = "?"
            rows.append([ts, tid, dur, b["ok"], b["fail"], rate, verdict])
        return rows

    # ── Panel 10: Charts（图表数据）───────────────────────────
    def _render_skill_refcount(self):
        """Skill 借出次数柱状图数据."""
        import pandas as pd
        if self._pool is None:
            return pd.DataFrame({"Skill": ["—"], "Refcount": [0]})
        health = self._pool.health_report()
        return pd.DataFrame(
            [{"Skill": n, "Refcount": h.get("refcount", 0)} for n, h in health.items()]
        )

    def _render_skill_health(self):
        """Skill 健康度（成功 vs 失败）堆叠柱状图数据."""
        import pandas as pd
        if self._pool is None:
            return pd.DataFrame({"Skill": ["—"], "Success": [0], "Failure": [0]})
        health = self._pool.health_report()
        return pd.DataFrame([
            {"Skill": n, "Success": h.get("health", {}).get("success", 0),
             "Failure": h.get("health", {}).get("failure", 0)}
            for n, h in health.items()
        ])

    def _render_event_timeline(self):
        """事件流时间序列（按分钟桶）折线图."""
        import pandas as pd
        from collections import Counter
        if self._bus is None:
            return pd.DataFrame({"minute": ["—"], "count": [0]})
        events = self._bus.recent(500)
        buckets: Counter = Counter()
        for e in events:
            ts = e.get("ts", "")[:16]
            if ts:
                buckets[ts] += 1
        return pd.DataFrame([{"minute": ts, "count": cnt} for ts, cnt in sorted(buckets.items())])

    def _render_event_type_pie(self):
        """事件类型分布柱状图（替代饼图）."""
        import pandas as pd
        from collections import Counter
        if self._bus is None:
            return pd.DataFrame({"type": ["—"], "count": [0]})
        events = self._bus.recent(500)
        cnt = Counter(e.get("type", "?").split(".")[-1] for e in events)
        return pd.DataFrame([{"type": t, "count": c} for t, c in cnt.most_common()])

    def _render_task_success_rate(self):
        """任务成功率时间序列（按分钟）."""
        import pandas as pd
        from collections import defaultdict
        if self._bus is None:
            return pd.DataFrame({"minute": ["—"], "ok": [0], "fail": [0], "rate": [0.0]})
        events = self._bus.recent(500)
        bucketed: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "fail": 0})
        for e in events:
            ts = e.get("ts", "")[:16]
            if not ts:
                continue
            if e.get("type") == EventType.TASK_COMPLETED.value:
                bucketed[ts]["ok"] += 1
            elif e.get("type") == EventType.TASK_FAILED.value:
                bucketed[ts]["fail"] += 1
        rows = []
        for ts in sorted(bucketed.keys()):
            ok = bucketed[ts]["ok"]
            fail = bucketed[ts]["fail"]
            rate = ok / (ok + fail) if (ok + fail) > 0 else 0.0
            rows.append({"minute": ts, "ok": ok, "fail": fail, "rate": round(rate, 3)})
        return pd.DataFrame(rows)

    # ── Panel 11: Reports（任务报告列表）───────────────────────────
    def _render_reports_list(self) -> list[list[str]]:
        """Reports 列表: [filename, task_id, mtime, size, has_pdf]."""
        if not self._reports_dir.exists():
            return [["—", "—", "—", "—", "—"]]
        rows = []
        for md_path in sorted(self._reports_dir.glob("t-*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                stat = md_path.stat()
                task_id = md_path.stem[2:]  # strip "t-"
                pdf_exists = md_path.with_suffix(".pdf").exists()
                rows.append([
                    md_path.name,
                    task_id,
                    datetime.fromtimestamp(stat.st_mtime).isoformat()[:19],
                    f"{stat.st_size}B",
                    "PDF" if pdf_exists else "—",
                ])
            except OSError:
                continue
        return rows if rows else [["—", "—", "No reports yet", "—", "—"]]

    def _render_report_content(self, selection) -> str:
        """读选中的 report 文件. selection 可以是 list (Dataframe) 或 str."""
        if selection is None:
            return "_请选择一份报告查看_"
        # Dataframe 选择返回 list-of-list 或 list-of-str
        if isinstance(selection, list):
            if not selection:
                return "_请选择一份报告查看_"
            first = selection[0]
            if isinstance(first, list):
                filename = first[0] if first else None
            else:
                filename = first
        else:
            filename = selection
        if not filename or filename == "—":
            return "_请选择一份报告查看_"
        path = self._reports_dir / filename
        if not path.exists() or not path.is_file():
            return f"_报告不存在: {filename}_"
        try:
            return path.read_text(encoding="utf-8")
        except Exception as exc:
            return f"_读取失败: {exc}_"

    # ── Panel 4: Health (Markdown) ─────────────────────────────
    def _render_health(self) -> str:
        """健康面板: Markdown 表格汇总."""
        if self._pool is None:
            return "**Pool not connected**"
        names = self._pool.list_available()
        health = self._pool.health_report()
        total_refcount = sum(h.get("refcount", 0) for h in health.values())
        total_success = sum(h.get("health", {}).get("success", 0) for h in health.values())
        total_failure = sum(h.get("health", {}).get("failure", 0) for h in health.values())
        ok = err = 0
        if self._bus is not None:
            for e in self._bus.recent(100):
                if e["type"] == EventType.TASK_COMPLETED.value:
                    ok += 1
                elif e["type"] == EventType.TASK_FAILED.value:
                    err += 1
        total_tasks = ok + err
        success_rate = ok / total_tasks if total_tasks else 1.0
        status_emoji = "🟢" if total_failure == 0 else "🟡" if total_failure < 5 else "🔴"
        status_text = "OK" if total_failure == 0 else "WARN" if total_failure < 5 else "DEGRADED"

        return (
            "### System Health\n\n"
            "| Metric | Value |\n|---|---|\n"
            f"| Skills Registered | **{len(names)}** |\n"
            f"| Active Borrows | {total_refcount} |\n"
            f"| Total Successes | {total_success} |\n"
            f"| Total Failures | {total_failure} |\n"
            f"| Tasks (recent 100) | {ok} ok / {err} fail |\n"
            f"| Task Success Rate | **{success_rate:.1%}** |\n"
            f"| Status | {status_emoji} **{status_text}** |\n"
        )

    # ── Panel 5: Submit Task (Progress + Error 分类) ───────────
    def _classify_error(self, exc: Exception) -> tuple[str, str]:
        """分类 Error → (html_message, css_class)."""
        if isinstance(exc, (ConnectionError, TimeoutError, asyncio.TimeoutError, OSError)):
            return (
                f'<div class="error-net"><b>Network Error</b>: {type(exc).__name__}: {exc}'
                f"<br><br>💡 检查服务是否在线 / 网络是否通畅"
                f"<br>示例: <code>systemctl status redis</code> 或 <code>curl &lt;api-endpoint&gt;</code></div>",
                "error-net",
            )
        if isinstance(exc, (KeyError, ValueError, TypeError, AttributeError)):
            return (
                f'<div class="error-param"><b>Parameter Error</b>: {type(exc).__name__}: {exc}'
                f"<br><br>💡 检查输入参数格式 / 必填字段</div>",
                "error-param",
            )
        return (
            f'<div class="error-system"><b>System Error</b>: {type(exc).__name__}: {exc}'
            f"<br><br>💡 查看日志: <code>tail -f {self._log_path}</code></div>",
            "error-system",
        )

    def _submit_task(
        self,
        request_text: str,
        target: str | None,
        progress: gr.Progress = gr.Progress(),
    ) -> tuple[str, str, str]:
        """提交任务 + Progress 回调 + Error 分类.

        Returns: (log_text, markdown_result, error_html)
        """
        if self._brain is None or self._pool is None:
            err = '<div class="error-system"><b>Brain/Pool not connected</b></div>'
            return "", "**Brain/Pool not connected**", err

        if not request_text or not request_text.strip():
            err = '<div class="error-param"><b>Parameter Error</b>: 任务描述不能为空</div>'
            return "", "**Parameter Error**: 任务描述不能为空", err

        try:
            from layers.work.transaction import TaskTransaction
            from layers.work.factory import AgentFactory
            from layers.work.skill_registry import register_needed_skills
            from layers.memory.store import MemoryStore, MemoryTier

            factory = AgentFactory(self._pool)
            plan = asyncio.run(self._brain.plan(request_text))
            register_needed_skills(self._pool, plan)

            subtasks = plan.subtasks
            results: list[str] = []
            progress(0.0, desc=f"Planning done. {len(subtasks)} subtasks queued.")

            with TaskTransaction(self._pool, factory, plan.task_id) as tx:
                for idx, sub in enumerate(subtasks):
                    progress(
                        (idx + 1) / max(len(subtasks), 1),
                        desc=f"[{idx + 1}/{len(subtasks)}] {sub.sub_id}",
                    )
                    inp: dict[str, Any] = {"topic": request_text}
                    if any(s.startswith("agentvet_") for s in sub.required_skills):
                        inp = {"target": target or "."}
                    r = tx.add(sub).run(inp)
                    status = "[OK]" if r.ok else "[FAIL]"
                    results.append(f"  {status} {r.sub_id}: {r.result or r.error}")

            if self._memory is not None:
                final = {
                    "task_id": plan.task_id,
                    "request": request_text,
                    "rationale": plan.rationale,
                    "results": results,
                    "all_ok": tx._result.all_ok,
                }
                self._memory.put(MemoryTier.LONG, f"task:{plan.task_id}", final)

            progress(1.0, desc="Done")
            header = f"**Task**: `{plan.task_id}`  \n**Rationale**: {plan.rationale}\n\n"
            log_text = header + "\n".join(results)
            return log_text, log_text, ""

        except Exception as exc:
            msg, css_class = self._classify_error(exc)
            progress(1.0, desc=f"Failed: {type(exc).__name__}")
            err_html = msg
            err_md = f"**{css_class.replace('error-', '').title()}**: {exc}"
            return "", err_md, err_html

    # ── Theme toggle ──────────────────────────────────────────
    def _toggle_theme(self, current: str) -> str:
        """切换 dark / light."""
        self._theme_mode = "light" if current == "dark" else "dark"
        return self._theme_mode

    # ── Launch ────────────────────────────────────────────────
    def launch(self, *, share: bool = False, prevent_thread_lock: bool = False) -> gr.Blocks:
        """启动战情看板 v2."""
        gr_themes = {
            "dark": gr.themes.Monochrome(),
            "light": gr.themes.Soft(),
        }
        # Gradio 6.0: theme + css 移到 launch() 方法
        demo = gr.Blocks(title="HiveSwarm 战情看板")

        with demo:
            # ── 顶部 StatusBar + Theme toggle ─────────
            with gr.Row(elem_classes="status-bar-row"):
                statusbar_html = gr.HTML(value=self._render_statusbar(), every=2)
            with gr.Row():
                with gr.Column(scale=10):
                    gr.Markdown("# 🐝 HiveSwarm 战情看板")
                with gr.Column(scale=0, min_width=120):
                    theme_state = gr.State(self._theme_mode)
                    theme_toggle = gr.Button("☀️ Light", size="sm")
                    theme_toggle.click(
                        fn=self._toggle_theme,
                        inputs=[theme_state],
                        outputs=[theme_state],
                    )

            # ── Tabs（顺序: Health→Submit→Tasks→Events→Skills）──
            with gr.Tabs():
                # Tab 1: Health（默认页 — 高频监控场景）
                with gr.TabItem("Health · 健康度"):
                    health_md = gr.Markdown(self._render_health, every=2)

                # Tab 2: Submit（执行任务入口 — 提交后跳到 Tasks 看进度）
                with gr.TabItem("Submit · 提交任务"):
                    gr.Markdown("### 提交新任务")
                    with gr.Row():
                        req_input = gr.Textbox(
                            label="任务描述",
                            placeholder="帮我做一个 PPT",
                            scale=4,
                        )
                        target_input = gr.Textbox(
                            label="扫描目标 (scan 类)",
                            placeholder=".",
                            value="",
                            scale=2,
                        )
                    submit_btn = gr.Button("▶ 执行", variant="primary")
                    result_md = gr.Markdown("等待任务...")
                    error_html = gr.HTML("", visible=False)
                    submit_btn.click(
                        fn=self._submit_task,
                        inputs=[req_input, target_input],
                        outputs=[result_md, result_md, error_html],
                    )

                # Tab 3: Tasks（执行中/已完成 列表 — Dataframe）
                with gr.TabItem("Tasks · 任务"):
                    tasks_df = gr.Dataframe(
                        headers=TASKS_HEADERS,
                        datatype=["str", "str", "str"],
                        value=self._render_tasks,
                        every=2,
                        interactive=False,
                        wrap=True,
                        elem_classes="dataframe",
                    )

                # Tab 4: Events（实时事件流）
                with gr.TabItem("Events · 事件流"):
                    events_md = gr.Markdown(self._render_events, every=2)

                # Tab 5: Skills（技能池状态 — Dataframe）
                with gr.TabItem("Skills · 技能池"):
                    skills_df = gr.Dataframe(
                        headers=SKILLS_HEADERS,
                        datatype=["str", "str", "number", "number", "number", "str"],
                        value=self._render_skills,
                        every=2,
                        interactive=False,
                        elem_classes="dataframe",
                    )

                # Tab 6: Brain
                with gr.TabItem("Brain"):
                    brain_df = gr.Dataframe(
                        headers=["Time", "Task ID", "Subs", "Status", "Dur", "Rationale", "Skills"],
                        datatype=["str", "str", "number", "str", "str", "str", "str"],
                        value=self._render_brain,
                        every=2,
                        interactive=False,
                        wrap=True,
                        elem_classes="dataframe",
                    )

                # Tab 7: Repair
                with gr.TabItem("Repair"):
                    repair_md = gr.Markdown(self._render_repair, every=2)

                # Tab 8: Memory
                with gr.TabItem("Memory"):
                    memory_md = gr.Markdown(self._render_memory, every=2)

                # Tab 9: Inspect
                with gr.TabItem("Inspect"):
                    inspect_df = gr.Dataframe(
                        headers=["Time", "Task ID", "Dur", "OK", "Fail", "Rate", "Verdict"],
                        datatype=["str", "str", "str", "number", "number", "str", "str"],
                        value=self._render_inspect,
                        every=2,
                        interactive=False,
                        wrap=True,
                        elem_classes="dataframe",
                    )

                # ── Tab 10: Charts（图表）──
                with gr.TabItem("Charts · 图表"):
                    gr.Markdown("### 实时图表 · 每 2 秒自动刷新")
                    with gr.Row():
                        skill_refcount_plot = gr.BarPlot(
                            value=self._render_skill_refcount,
                            x="Skill", y="Refcount",
                            title="Skill 当前借出数（柱状图）",
                            every=2, height=300,
                        )
                    with gr.Row():
                        skill_health_plot = gr.BarPlot(
                            value=self._render_skill_health,
                            x="Skill", y="Success",
                            title="Skill 健康度（成功 vs 失败，堆叠柱状图）",
                            every=2, height=300,
                        )
                    with gr.Row():
                        event_timeline_plot = gr.LinePlot(
                            value=self._render_event_timeline,
                            x="minute", y="count",
                            title="事件流时间分布（按分钟，折线图）",
                            every=2, height=300,
                        )
                    with gr.Row():
                        with gr.Column(scale=1):
                            event_pie = gr.BarPlot(
                                value=self._render_event_type_pie,
                                x="type", y="count",
                                title="事件类型分布（柱状图代替饼图）",
                                every=2, height=300,
                            )
                        with gr.Column(scale=2):
                            task_rate_plot = gr.LinePlot(
                                value=self._render_task_success_rate,
                                x="minute", y="rate",
                                title="任务成功率时间序列（折线图）",
                                every=2, height=300,
                            )

                # ── Tab 11: Reports（任务报告）──
                with gr.TabItem("Reports · 报告"):
                    gr.Markdown("### 详细任务执行报告 · 每 2 秒自动刷新")
                    reports_df = gr.Dataframe(
                        headers=["File", "Task ID", "Generated", "Size", "PDF"],
                        datatype=["str", "str", "str", "str", "str"],
                        value=self._render_reports_list,
                        every=2,
                        interactive=False,
                        wrap=True,
                        elem_classes="dataframe",
                    )
                    report_md = gr.Markdown("**选中左侧任务 ID 可在此处显示报告内容**")
                    reports_df.change(
                        fn=self._render_report_content,
                        inputs=[reports_df],
                        outputs=[report_md],
                    )

        self._demo = demo
        demo.launch(
            server_port=self.port,
            share=share,
            theme=gr_themes[self._theme_mode],
            css=CUSTOM_CSS,
            prevent_thread_lock=prevent_thread_lock,
        )
        return demo

    def snapshot(self) -> dict[str, Any]:
        """快照 (给非 GUI 环境)."""
        names = self._pool.list_available() if self._pool else []
        health = self._pool.health_report() if self._pool else {}
        return {
            "skills": len(names),
            "health": health,
            "port": self.port,
            "theme": self._theme_mode,
        }