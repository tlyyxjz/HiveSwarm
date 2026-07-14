"""ReportGenerator — 任务完成后生成 Markdown + PDF 报告.

设计目标:
- 客户能直接读懂（业务语言, 不暴露内部 skill 名/事件类型）
- 包含执行摘要 + 详细时间线 + 分析 + 风险 + 建议
- Markdown 主输出（可读）, PDF 备用（可发）
- 失败时优雅降级: PDF 不可用则只写 Markdown
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from core.events import EventType

_log = logging.getLogger(__name__)


@dataclass
class Report:
    """生成的报告对象."""

    task_id: str
    md_path: Path | None = None
    pdf_path: Path | None = None
    title: str = "任务执行报告"
    generated_at: str = ""
    content_md: str = ""  # 原始 Markdown 文本


class ReportGenerator:
    """从 EventBus + 任务结果拼报告."""

    def __init__(
        self,
        bus,                    # EventBus 实例
        memory=None,            # MemoryStore 可选
        reports_dir: str = "~/.hiveswarm/reports",
    ) -> None:
        self._bus = bus
        self._memory = memory
        self._reports_dir = Path(reports_dir).expanduser()
        self._reports_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        task_id: str,
        request: str,
        result: dict[str, Any] | None = None,
        title: str = "任务执行报告",
    ) -> Report:
        """生成报告: 拼 Markdown + 写盘 + 尝试 PDF + 存 memory.

        Args:
            task_id: 任务 ID
            request: 客户原始请求
            result: 任务执行结果 dict (从 run_demo 返回)
            title: 报告标题
        """
        result = result or {}
        events = self._collect_events(task_id)
        analysis = self._analyze(events, result)
        md = self._render_markdown(task_id, request, result, events, analysis, title)

        # 写 Markdown
        md_path = self._reports_dir / f"t-{task_id}.md"
        md_path.write_text(md, encoding="utf-8")

        # 尝试写 PDF
        pdf_path = None
        try:
            pdf_path = self._render_pdf(md_path, task_id, title)
        except Exception as exc:  # noqa: BLE001
            _log.warning("PDF 生成失败, 仅 Markdown 可用: %s", exc)

        # 存 memory
        if self._memory is not None:
            try:
                from layers.memory.store import MemoryTier
                self._memory.put(
                    MemoryTier.WORKING,
                    f"report:{task_id}",
                    {"md": str(md_path), "pdf": str(pdf_path) if pdf_path else None},
                )
            except Exception as exc:  # noqa: BLE001
                _log.warning("memory 存报告失败: %s", exc)

        return Report(
            task_id=task_id,
            md_path=md_path,
            pdf_path=pdf_path,
            title=title,
            generated_at=datetime.now().isoformat(),
            content_md=md,
        )

    # ── 数据收集 ────────────────────────────────────────────

    def _collect_events(self, task_id: str) -> list[dict]:
        """从 bus 拉这个 task 的所有事件."""
        if self._bus is None:
            return []
        all_evts = self._bus.recent(1000)
        return [e for e in all_evts if e.get("task_id") == task_id]

    # ── 分析 ─────────────────────────────────────────────────

    def _analyze(self, events: list[dict], result: dict) -> dict:
        """从事件 + 结果里提炼亮点 / 风险 / 建议."""
        started_at = None
        ended_at = None
        sub_count = 0
        sub_fail = 0
        skills_used: set[str] = set()

        for e in events:
            t = e.get("ts")
            if e.get("type") == EventType.TASK_STARTED.value and t:
                started_at = started_at or t
            if e.get("type") in (EventType.TASK_COMPLETED.value, EventType.TASK_FAILED.value) and t:
                ended_at = t
            if e.get("type") == EventType.TASK_STARTED.value:
                sub_count += 1
            if e.get("type") == EventType.TASK_FAILED.value:
                sub_fail += 1
            for s in e.get("names", []) or []:
                skills_used.add(s)

        duration_s = 0.0
        if started_at and ended_at:
            try:
                t0 = datetime.fromisoformat(started_at)
                t1 = datetime.fromisoformat(ended_at)
                duration_s = (t1 - t0).total_seconds()
            except Exception:  # noqa: BLE001
                pass

        highlights: list[str] = []
        risks: list[str] = []
        suggestions: list[str] = []

        # 亮点
        if result.get("all_ok"):
            highlights.append(f"所有 {sub_count} 个子任务成功完成")
        if duration_s and duration_s < 60:
            highlights.append(f"执行高效, 总耗时 {duration_s:.1f}s")
        if len(skills_used) >= 2:
            highlights.append(f"使用了 {len(skills_used)} 个技能协同工作")

        # 风险
        if sub_fail > 0:
            risks.append(f"{sub_fail} 个子任务失败 (自动修复或重试)")
        if duration_s and duration_s > 300:
            risks.append(f"执行时间偏长 ({duration_s/60:.1f} 分钟), 可能存在瓶颈")

        # 建议
        if sub_fail > 0:
            suggestions.append("重新提交任务可触发 Repair 模块自动修复")
        if not result.get("all_ok"):
            suggestions.append("查看 Dashboard Repair Tab 看具体修复建议")

        return {
            "duration_s": duration_s,
            "started_at": started_at,
            "ended_at": ended_at,
            "sub_count": sub_count,
            "sub_fail": sub_fail,
            "skills_used": sorted(skills_used),
            "highlights": highlights,
            "risks": risks,
            "suggestions": suggestions,
        }

    # ── Markdown 渲染 ───────────────────────────────────────

    def _render_markdown(
        self,
        task_id: str,
        request: str,
        result: dict,
        events: list[dict],
        a: dict,
        title: str,
    ) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines: list[str] = []
        # 标题
        lines.append(f"# {title}")
        lines.append("")
        lines.append(f"> **任务 ID**: `{task_id}`  ")
        lines.append(f"> **生成时间**: {now}  ")
        lines.append(f"> **HiveSwarm 版本**: v0.2.0")
        lines.append("")

        # 📌 基本信息
        lines.append("## 📌 基本信息")
        lines.append("")
        lines.append(f"- **客户请求**: {request}")
        if a["started_at"]:
            lines.append(f"- **开始时间**: {a['started_at'][:19]}")
        if a["ended_at"]:
            lines.append(f"- **结束时间**: {a['ended_at'][:19]}")
        if a["duration_s"]:
            lines.append(f"- **总耗时**: {a['duration_s']:.1f}s")
        lines.append(f"- **拆解子任务**: {a['sub_count']}")
        lines.append(f"- **使用技能**: {', '.join(a['skills_used']) or '—'}")
        lines.append("")

        # 📊 执行详情
        lines.append("## 📊 执行详情")
        lines.append("")
        lines.append("| 子任务 | 技能 | 输入 | 状态 | 摘要 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for r in result.get("results", []):
            sub_id = r.get("sub_id", "?")
            ok = r.get("ok", False)
            status = "✅" if ok else "❌"
            err = r.get("error") or ""
            res = r.get("result") or {}
            # 把 dict 结果压一行
            if isinstance(res, dict):
                # 取第一个 value 作为摘要
                summary = next(iter(res.values()), "") if res else ""
                if isinstance(summary, (dict, list)):
                    summary = json_dumps_short(summary)
                summary = str(summary)[:60]
            else:
                summary = str(res)[:60]
            # 推断技能
            skill = "—"
            for s in a["skills_used"]:
                if s.startswith(sub_id.split("_")[0]) or sub_id in s:
                    skill = s
                    break
            lines.append(f"| {sub_id} | {skill} | (auto) | {status}{(' ('+err[:30]+')') if err else ''} | {summary or '—'} |")
        lines.append("")

        # 💡 分析
        lines.append("## 💡 分析")
        lines.append("")
        if a["highlights"]:
            lines.append("**亮点**:")
            for h in a["highlights"]:
                lines.append(f"- ✅ {h}")
            lines.append("")
        if a["risks"]:
            lines.append("**风险**:")
            for r in a["risks"]:
                lines.append(f"- ⚠️ {r}")
            lines.append("")
        if a["suggestions"]:
            lines.append("**建议**:")
            for s in a["suggestions"]:
                lines.append(f"- 💡 {s}")
            lines.append("")
        if not (a["highlights"] or a["risks"] or a["suggestions"]):
            lines.append("_无特别分析_")
            lines.append("")

        # ✅ 客户结论
        lines.append("## ✅ 客户结论")
        lines.append("")
        if result.get("all_ok"):
            lines.append(f"**任务成功完成**。{a['sub_count']} 个子任务全部通过, 总耗时 {a['duration_s']:.1f}s。")
        else:
            lines.append(f"**任务部分失败**。{a['sub_fail']} 个子任务失败, 已尝试自动修复。")
        lines.append("")
        lines.append("**下一步**:")
        lines.append("- 查看 Dashboard 了解更多详情")
        lines.append("- 重新提交任务可触发 Repair 重调度")
        lines.append("- 报告同时存为 Markdown 和 PDF")
        lines.append("")

        # 附录
        lines.append("---")
        lines.append(f"_本报告由 HiveSwarm ReportGenerator 自动生成 @ {now}_")
        return "\n".join(lines)

    # ── PDF 渲染 ────────────────────────────────────────────

    def _render_pdf(self, md_path: Path, task_id: str, title: str) -> Path:
        """用 reportlab 把 markdown 文本转 PDF."""
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.units import cm
        from reportlab.lib.enums import TA_LEFT

        pdf_path = md_path.with_suffix(".pdf")
        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            leftMargin=2*cm, rightMargin=2*cm,
            topMargin=2*cm, bottomMargin=2*cm,
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "Title", parent=styles["Title"],
            fontSize=20, textColor="#0F172A", alignment=TA_LEFT,
        )
        h2_style = ParagraphStyle(
            "H2", parent=styles["Heading2"],
            fontSize=14, textColor="#0891B2", spaceBefore=12,
        )
        body_style = ParagraphStyle(
            "Body", parent=styles["BodyText"],
            fontSize=11, leading=16, textColor="#0F172A",
        )
        code_style = ParagraphStyle(
            "Code", parent=styles["Code"],
            fontSize=9, leading=13,
        )

        story: list = [Paragraph(title, title_style), Spacer(1, 12)]
        md_text = md_path.read_text(encoding="utf-8")

        for line in md_text.split("\n"):
            line = line.strip()
            if not line:
                story.append(Spacer(1, 6))
                continue
            if line.startswith("# "):
                continue  # 标题已加
            if line.startswith("## "):
                story.append(Paragraph(line[3:], h2_style))
            elif line.startswith("> "):
                story.append(Paragraph("<i>" + line[2:] + "</i>", body_style))
            elif line.startswith("- "):
                story.append(Paragraph("• " + line[2:], body_style))
            elif line.startswith("|"):
                # 表格行 — 简化: 跳过 (PDF 表格要 Table 对象)
                pass
            elif line.startswith("---"):
                story.append(Spacer(1, 12))
            else:
                # 转义 < 和 >
                safe = line.replace("<", "&lt;").replace(">", "&gt;")
                story.append(Paragraph(safe, body_style))

        doc.build(story)
        return pdf_path


def json_dumps_short(obj: Any, limit: int = 60) -> str:
    """把对象压成短字符串."""
    import json
    try:
        s = json.dumps(obj, ensure_ascii=False)
        return s[:limit]
    except Exception:  # noqa: BLE001
        return str(obj)[:limit]