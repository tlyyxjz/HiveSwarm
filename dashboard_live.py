import gradio as gr
import json, os, subprocess
from pathlib import Path

HOME = Path.home()
HIVE = HOME / ".claude/data/hive-mind.json"
DISPATCH = HOME / ".claude/data/hive-dispatch.json"
PRESETS = HOME / ".claude/config/swarm-presets.json"
SCRIPTS = HOME / ".claude/scripts"

def get_presets():
    try: return json.loads(PRESETS.read_text(encoding="utf-8"))
    except: return {"presets":{}}

def get_data():
    try:
        hive = json.loads(HIVE.read_text(encoding="utf-8"))
        dispatch = json.loads(DISPATCH.read_text(encoding="utf-8"))
    except: hive, dispatch = {}, {}

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
    return agent_html or "无", findings_html or "暂无", len(findings), dispatch.get("mode","idle"), dispatch.get("topology","?"), q, d, hive.get("mission","?")[:100]

def launch_preset(preset_name, target_url):
    """从面板一键发起蜂群"""
    if not target_url:
        return "请输入目标URL", ""
    cmd = f'python {str(SCRIPTS)}/hive-mind.py presets --use {preset_name} --target "{target_url}"'
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        result = r.stdout.strip()
        # Also run brain
        subprocess.run(f'python {str(SCRIPTS)}/hive-brain.py --target "{target_url}"', shell=True, capture_output=True, timeout=10)
        # Update hive data
        hive = json.loads(HIVE.read_text(encoding="utf-8"))
        agents_list = [a for a in hive.get("agent_queue",[])]
        return f"蜂群已发起! {preset_name}\n{result}", ", ".join(agents_list) if agents_list else "无"
    except Exception as e:
        return f"发起失败: {e}", ""

def launch_ad_hoc(agents_str, target_url):
    """现场组队"""
    if not agents_str or not target_url:
        return "请输入Agent列表和目标URL", ""
    cmd = f'python {str(SCRIPTS)}/hive-mind.py swarm --agents "{agents_str}" --target "{target_url}"'
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return f"现场组队已发起!\n{r.stdout.strip()[:300]}"
    except Exception as e:
        return f"发起失败: {e}"

def run_brain(target_url):
    """跑brain分析"""
    if not target_url:
        return "请输入目标URL", ""
    cmd = f'python {str(SCRIPTS)}/hive-brain.py --target "{target_url}" --url "{target_url}" --execute 2>/dev/null'
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        out = r.stdout[-500:] if len(r.stdout) > 500 else r.stdout
        # Also read hive
        hive = json.loads(HIVE.read_text(encoding="utf-8")) if HIVE.exists() else {}
        queue = ", ".join(hive.get("agent_queue",[])) or "空"
        return f"Brain分析完成\n{out}", queue
    except Exception as e:
        return f"Brain分析失败: {e}", ""

# ── 构建UI ──
# 预设列表
ps = get_presets()
preset_choices = list(ps.get("presets", {}).keys())
preset_labels = {k: f"{v.get('label','?')} ({len(v.get('agents',[]))}Agent)" for k,v in ps.get("presets",{}).items()}

with gr.Blocks(title="HiveSwarm 实时战况") as demo:
    gr.Markdown("# HiveSwarm 实时战况")
    mission_txt = gr.Textbox(label="任务", interactive=False)

    with gr.Tabs():
        # Tab 1: 实时状态
        with gr.TabItem("实时战况"):
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

        # Tab 2: 组合技控制台
        with gr.TabItem("组合技"):
            gr.Markdown("## 一键发起蜂群")
            target_input = gr.Textbox(label="目标URL", placeholder="https://ctf.hacker101.com/...")
            
            with gr.Row():
                preset_dropdown = gr.Dropdown(
                    choices=list(preset_labels.keys()),
                    label="预设组合技",
                    value=list(preset_labels.keys())[0] if preset_labels else None
                )
                btn_preset = gr.Button("一键发起", variant="primary")
            preset_result = gr.Textbox(label="结果", interactive=False)
            preset_queue = gr.Textbox(label="Agent列表", interactive=False)
            
            gr.Markdown("---")
            gr.Markdown("## 现场组队（任意组合）")
            agents_input = gr.Textbox(label="Agent列表 (逗号分隔)", placeholder="api-hunter,sql-injector,xss-hunter,waf-bypasser")
            btn_ad_hoc = gr.Button("现场组队", variant="secondary")
            ad_hoc_result = gr.Textbox(label="结果", interactive=False)

            gr.Markdown("---")
            gr.Markdown("## Brain分析")
            btn_brain = gr.Button("Brain分析", variant="secondary")
            brain_result = gr.Textbox(label="Brain输出", interactive=False)
            brain_queue = gr.Textbox(label="选出的Agent", interactive=False)

        # Tab 3: 预设速查
        with gr.TabItem("预设速查"):
            for pname, pcfg in sorted(ps.get("presets",{}).items()):
                agents_str = ", ".join(pcfg.get("agents",[]))
                triggers = " | ".join(pcfg.get("trigger",[]) or [])[:80]
                gr.Markdown(f"**{pcfg.get('label',pname)}**")
                gr.Markdown(f"> Agent: {agents_str}")
                gr.Markdown(f"> 触发: {triggers}")
                gr.Markdown("---")

    # 事件绑定
    timer = gr.Timer(2)
    timer.tick(get_data, outputs=[agents_disp, findings_disp, total, mode_disp, topo_disp, queue_disp, done_disp, mission_txt])

    btn_preset.click(launch_preset, inputs=[preset_dropdown, target_input], outputs=[preset_result, preset_queue])
    btn_ad_hoc.click(launch_ad_hoc, inputs=[agents_input, target_input], outputs=[ad_hoc_result])
    btn_brain.click(run_brain, inputs=[target_input], outputs=[brain_result, brain_queue])

demo.launch(server_port=7860, share=False, theme=gr.themes.Soft())
