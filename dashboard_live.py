import gradio as gr
import json
from pathlib import Path

HOME = Path.home()
HIVE = HOME / ".claude/data/hive-mind.json"
DISPATCH = HOME / ".claude/data/hive-dispatch.json"

def get_data():
    try:
        hive = json.loads(HIVE.read_text(encoding="utf-8"))
        dispatch = json.loads(DISPATCH.read_text(encoding="utf-8"))
    except:
        hive, dispatch = {}, {}

    agents = []
    for a, s in hive.get("agent_states", {}).items():
        agents.append({"name": a, "status": s.get("status","?"), "findings": s.get("findings",0)})

    findings = hive.get("findings", [])
    findings_html = ""
    for f in findings[-5:]:
        sev = f.get("severity", "info").upper()
        color = {"CRITICAL":"#dc2626","HIGH":"#f97316","MEDIUM":"#eab308"}.get(sev,"#64748b")
        findings_html += f'<div style="background:#1a1212;border-left:3px solid {color};padding:6px 10px;margin:4px 0;border-radius:4px"><b style="color:{color}">[{sev}]</b> {f.get("type","?")[:50]}<br><span style="color:#64748b;font-size:.8em">{f.get("agent","?")}</span></div>'

    agent_html = ""
    for a in agents:
        c = "22c55e" if a['status']=='hunting' else ("64748b" if a['status']=='done' else "eab308")
        agent_html += f'<div style="display:flex;align-items:center;gap:6px;padding:4px 0;font-size:.9em"><span style="width:8px;height:8px;border-radius:50%;background:#{c};box-shadow:0 0 4px #{c}"></span><b>{a["name"]}</b> {a["status"]} | {a["findings"]}发现</div>'

    q = ", ".join(hive.get("agent_queue",[])) or "空"
    d = ", ".join(hive.get("completed_agents",[])) or "无"
    return agent_html or "无", findings_html or "暂无", len(findings), dispatch.get("mode","idle"), dispatch.get("topology","?"), q, d, hive.get("mission","?")[:60]

with gr.Blocks(title="HiveSwarm 实时战况") as demo:
    gr.Markdown("# HiveSwarm 实时战况")
    mission_txt = gr.Textbox(label="任务", interactive=False)
    with gr.Row():
        agents_disp = gr.HTML(label="Agent状态")
        findings_disp = gr.HTML(label="最近发现")
    with gr.Row():
        total = gr.Number(label="发现总数")
        mode_disp = gr.Textbox(label="模式")
        topo_disp = gr.Textbox(label="拓扑")
    with gr.Row():
        queue_disp = gr.Textbox(label="队列")
        done_disp = gr.Textbox(label="已完成")
    timer = gr.Timer(2)
    timer.tick(get_data, outputs=[agents_disp, findings_disp, total, mode_disp, topo_disp, queue_disp, done_disp, mission_txt])

demo.launch(server_port=7860, share=False, theme=gr.themes.Soft())
