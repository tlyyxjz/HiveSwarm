#!/usr/bin/env python3
"""hive-live — 实时战况面板。每次Agent/PI动作后更新。"""
import json, sys, os
from pathlib import Path
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
HOME = Path.home()
DASHBOARD = HOME / ".claude/data/live-dashboard.json"
HIVE = HOME / ".claude/data/hive-mind.json"
DISPATCH = HOME / ".claude/data/hive-dispatch.json"
STATE = HOME / ".claude/data/overseer-state.json"

def build():
    now = datetime.now(TZ).strftime("%H:%M:%S")
    hive = json.loads(HIVE.read_text(encoding="utf-8")) if HIVE.exists() else {}
    dispatch = json.loads(DISPATCH.read_text(encoding="utf-8")) if DISPATCH.exists() else {}
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}

    agents = []
    for a, s in hive.get("agent_states", {}).items():
        agents.append({"name": a, "status": s.get("status","?"), "findings": s.get("findings",0)})

    queue = hive.get("agent_queue", [])
    done = hive.get("completed_agents", [])
    findings = len(hive.get("findings", []))
    findings_list = hive.get("findings", [])[-5:]  # last 5

    dashboard = {
        "ts": now,
        "mission": hive.get("mission", "?")[:60],
        "mode": dispatch.get("mode", "idle"),
        "topology": dispatch.get("topology", "parallel"),
        "label": dispatch.get("label", ""),
        "agents": agents,
        "queue": queue,
        "done": done,
        "findings_count": findings,
        "last_findings": findings_list,
        "pi_used": state.get("total_bash", 0) > state.get("total_bash", 0) - 1 if state.get("total_bash",0) else False,
        "bash_streak": state.get("bash_streak", 0),
        "pi_warns": state.get("pi_warn", 0),
        "pi_total_violations": state.get("pi_violations", 0),
    }
    DASHBOARD.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2), encoding="utf-8")
    return dashboard

def show():
    d = build()
    print("=" * 55)
    print(f"  蜂巢实时战况  {d['ts']}")
    print("=" * 55)
    print(f"  任务: {d['mission']}")
    print(f"  模式: {d['mode']} | 拓扑: {d['topology']} | {d['label']}")
    print(f"  发现: {d['findings_count']} 个")
    print(f"  队列: {d['queue']} | 已完成: {d['done']}")
    print()
    if d['agents']:
        print(f"  AGENT 状态:")
        for a in d['agents']:
            icon = "GREEN" if a['status']=='hunting' else "WHITE" if a['status']=='done' else "YELLOW"
            print(f"    [{icon}] {a['name']}: {a['status']} | {a['findings']} findings")
    else:
        print(f"  AGENT 状态: 无活跃Agent")

    print()
    print(f"  PI 状态:")
    print(f"    Bash连用: {d['bash_streak']}/3 (>=3触发强制派PI)")
    print(f"    PI违规累计: {d['pi_total_violations']}")
    print(f"    下次Bash{'已阻断' if d['bash_streak'] >= 3 else '可继续'}")

    if d['last_findings']:
        print(f"\n  最近发现:")
        for f in d['last_findings']:
            sev = f.get('severity','?').upper()
            print(f"    [{sev}] {f.get('type','?')[:40]} | {f.get('agent','?')}")

    print("=" * 55)

if __name__ == "__main__":
    if "--show" in sys.argv:
        show()
    else:
        show()
