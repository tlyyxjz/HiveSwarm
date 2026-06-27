"""GradioDashboard — 战情看板 (Day 6-8 实装).

5 面板: Skills | Tasks | Events | Health | Submit
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import gradio as gr

from core.events import EventType
from core.brain import Plan, SubTask


class GradioDashboard:
    """Gradio 战情看板. 5 面板实时监控 HiveSwarm."""

    def __init__(
        self,
        pool=None,
        bus=None,
        brain=None,
        memory=None,
        port: int = 7860,
        log_path: str = "~/.hiveswarm/logs/events.jsonl",
    ) -> None:
        self.port = port
        self._pool = pool
        self._bus = bus
        self._brain = brain
        self._memory = memory
        self._log_path = Path(log_path).expanduser()
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Panel 1: Skills ──────────────────────────────────────────────

    def _render_skills(self) -> str:
        """技能面板: 已注册技能的表格."""
        if self._pool is None:
            return "Pool not connected"
        health = self._pool.health_report()
        names = self._pool.list_available()
        if not names:
            return "No skills registered yet"

        rows = ["| Skill | API | Refcount | Success | Failure | Error Rate |",
                "|-------|-----|----------|---------|---------|------------|"]
        for name in names:
            m = self._pool.get_manifest(name)
            h = health.get(name, {})
            hh = h.get("health", {})
            rows.append(
                f"| {name} | {m.get('api_version','?') if m else '?'} "
                f"| {h.get('refcount',0)} "
                f"| {hh.get('success',0)} "
                f"| {hh.get('failure',0)} "
                f"| {hh.get('error_rate',0):.1%} |"
            )
        return "\n".join(rows)

    # ── Panel 2: Tasks ───────────────────────────────────────────────

    def _render_tasks(self, n: int = 10) -> str:
        """任务面板: 最近 N 个任务的概览."""
        if self._bus is None:
            return "Bus not connected"

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
            return "No task events yet"

        rows = ["| Time | Type | Details |",
                "|------|------|---------|"]
        for e in task_events[-n:]:
            ts = e.get("ts", "")[:19]
            rows.append(f"| {ts} | {e['type']} | {json.dumps(e, ensure_ascii=False)[:80]} |")
        return "\n".join(rows)

    # ── Panel 3: Events ──────────────────────────────────────────────

    def _render_events(self, n: int = 20) -> str:
        """事件面板: 最近事件的文本流."""
        if self._bus is None:
            return "Bus not connected"

        events = self._bus.recent(n)
        if not events:
            return "No events yet"

        lines = []
        for e in events:
            ts = e.get("ts", "")[:19]
            etype = e.get("type", "?")
            lines.append(f"[{ts}] {etype}")
        return "\n".join(lines)

    # ── Panel 4: Health ──────────────────────────────────────────────

    def _render_health(self) -> str:
        """健康面板: 全局指标汇总."""
        if self._pool is None:
            return "Pool not connected"

        names = self._pool.list_available()
        health = self._pool.health_report()

        total_refcount = sum(h.get("refcount", 0) for h in health.values())
        total_success = sum(h.get("health", {}).get("success", 0) for h in health.values())
        total_failure = sum(h.get("health", {}).get("failure", 0) for h in health.values())

        # Task stats from bus
        ok = err = 0
        if self._bus is not None:
            for e in self._bus.recent(100):
                if e["type"] == EventType.TASK_COMPLETED.value:
                    ok += 1
                elif e["type"] == EventType.TASK_FAILED.value:
                    err += 1

        return (
            f"**Pool**: {len(names)} skills registered, {total_refcount} active borrows\n\n"
            f"**Skills**: {total_success} successes, {total_failure} failures\n\n"
            f"**Tasks (recent 100)**: {ok} completed, {err} failed\n\n"
            f"**Status**: {'OK' if total_failure == 0 else 'WARN'}"
        )

    # ── Panel 5: Submit Task ─────────────────────────────────────────

    def _submit_task(self, request_text: str, target: str | None = None) -> str:
        """提交任务表单."""
        if self._brain is None or self._pool is None:
            return "Brain/Pool not connected"

        try:
            from layers.work.transaction import TaskTransaction
            from layers.work.factory import AgentFactory
            from layers.work.skill_registry import register_needed_skills
            from layers.memory.store import MemoryStore, MemoryTier
            import asyncio

            factory = AgentFactory(self._pool)
            plan = asyncio.run(self._brain.plan(request_text))
            register_needed_skills(self._pool, plan)

            results = []
            with TaskTransaction(self._pool, factory, plan.task_id) as tx:
                for sub in plan.subtasks:
                    inp = {"topic": request_text}
                    if any(s.startswith("agentvet_") for s in sub.required_skills):
                        inp = {"target": target or "."}
                    r = tx.add(sub).run(inp)
                    results.append(f"  {'[OK]' if r.ok else '[FAIL]'} {r.sub_id}: {r.result or r.error}")

            if self._memory is not None:
                final = {
                    "task_id": plan.task_id,
                    "request": request_text,
                    "rationale": plan.rationale,
                    "results": results,
                    "all_ok": tx._result.all_ok,
                }
                self._memory.put(MemoryTier.LONG, f"task:{plan.task_id}", final)

            header = f"Task: {plan.task_id}\nRationale: {plan.rationale}\n"
            return header + "\n".join(results)

        except Exception as exc:
            return f"Error: {exc}"

    # ── Launch ───────────────────────────────────────────────────────

    def launch(self, *, share: bool = False) -> gr.Blocks:
        """启动战情看板."""
        with gr.Blocks(title="HiveSwarm 战情看板", theme=gr.themes.Soft()) as demo:
            gr.Markdown("# 🐝 HiveSwarm 战情看板")

            with gr.Tabs():
                with gr.TabItem("技能池"):
                    gr.Markdown("### 已注册技能")
                    skills_md = gr.Markdown("Loading...")
                    skills_btn = gr.Button("刷新")
                    skills_btn.click(fn=self._render_skills, outputs=skills_md)

                with gr.TabItem("任务"):
                    gr.Markdown("### 最近任务")
                    tasks_md = gr.Markdown("Loading...")
                    tasks_btn = gr.Button("刷新")
                    tasks_btn.click(fn=lambda: self._render_tasks(10), outputs=tasks_md)

                with gr.TabItem("事件流"):
                    gr.Markdown("### 实时事件")
                    events_md = gr.Markdown("Loading...")
                    events_btn = gr.Button("刷新")
                    events_btn.click(fn=lambda: self._render_events(20), outputs=events_md)

                with gr.TabItem("健康度"):
                    gr.Markdown("### 系统健康")
                    health_md = gr.Markdown("Loading...")
                    health_btn = gr.Button("刷新")
                    health_btn.click(fn=self._render_health, outputs=health_md)

                with gr.TabItem("提交任务"):
                    gr.Markdown("### 提交新任务")
                    req_input = gr.Textbox(label="任务描述", placeholder="帮我做一个 PPT")
                    target_input = gr.Textbox(label="扫描目标 (scan 类)", value="")
                    submit_btn = gr.Button("执行")
                    result_output = gr.Markdown("等待任务...")
                    submit_btn.click(
                        fn=self._submit_task,
                        inputs=[req_input, target_input],
                        outputs=result_output,
                    )

            # Initial render
            demo.load(
                fn=self._render_skills, outputs=skills_md
            ).then(
                fn=lambda: self._render_tasks(10), outputs=tasks_md
            ).then(
                fn=lambda: self._render_events(20), outputs=events_md
            ).then(
                fn=self._render_health, outputs=health_md
            )

        self._demo = demo
        demo.launch(server_port=self.port, share=share)
        return demo

    def snapshot(self) -> dict[str, Any]:
        """快照 (给非 GUI 环境)."""
        names = self._pool.list_available() if self._pool else []
        health = self._pool.health_report() if self._pool else {}
        return {
            "skills": len(names),
            "health": health,
            "port": self.port,
        }