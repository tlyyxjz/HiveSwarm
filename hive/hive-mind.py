#!/usr/bin/env python3
"""
hive-mind.py — 蜂巢共享大脑
所有Agent的输入/输出/发现/状态全在这里，谁要谁调用。

用法:
  python hive-mind.py init "审计 https://example.com"  → 创建新任务
  python hive-mind.py read                              → 读取当前状态
  python hive-mind.py write agent xss-hunter --finding   → agent写入发现
  python hive-mind.py claim xss-hunter /search           → agent认领端点
  python hive-mind.py queue --add api-hunter              → 加入Agent队列
  python hive-mind.py status                              → 蜂群状态一览
  python hive-mind.py swarm --agents api,sqli,xss,waf --target URL  → 现场组队
  python hive-mind.py presets                              → 列出所有预设
  python hive-mind.py presets --use full_web_audit --target URL  → 用预设组队
"""
import json, sys, os, uuid, argparse, subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
HOME = Path.home()
DATA = HOME / ".claude/data"
HIVE_FILE = str(HOME / ".claude/scripts/hive-mind.py")
HIVE_AGENT = str(HOME / ".claude/scripts/hive-agent.py")
HIVE = DATA / "hive-mind.json"
DATA.mkdir(parents=True, exist_ok=True)

def timestamp():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

def load():
    if HIVE.exists():
        return json.loads(HIVE.read_text(encoding="utf-8"))
    return None

def save(data):
    data["_updated"] = timestamp()
    HIVE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ─── 命令 ───

def cmd_init(args):
    data = {
        "mission": args.target,
        "phase": "recon",
        "created": timestamp(),
        "_updated": timestamp(),
        "targets": [],
        "attack_surface": {
            "endpoints": [],
            "params": [],
            "headers": [],
            "tech_stack": [],
            "waf": None,
        },
        "findings": [],
        "agent_states": {},
        "agent_queue": [],
        "completed_agents": [],
        "notes": [],
    }
    save(data)
    print(f"[HIV] 蜂巢已初始化: {args.target}")

def cmd_read(_args):
    data = load()
    if not data:
        print(json.dumps({"status": "empty"}, ensure_ascii=False))
        return
    print(json.dumps(data, ensure_ascii=False, indent=2))

def cmd_write(args):
    data = load()
    if not data:
        print("? 蜂巢未初始化，先 init")
        return

    if args.finding:
        finding = {
            "id": uuid.uuid4().hex[:8],
            "agent": args.agent,
            "type": args.type or "info",
            "severity": args.severity or "info",
            "endpoint": args.endpoint or "",
            "detail": args.detail or "",
            "payload": args.payload or "",
            "confirmed": False,
            "ts": timestamp(),
        }
        data["findings"].append(finding)
        # 同时更新agent状态
        if args.agent not in data["agent_states"]:
            data["agent_states"][args.agent] = {"status": "active", "findings": 0, "last_update": timestamp()}
        data["agent_states"][args.agent]["findings"] += 1
        data["agent_states"][args.agent]["last_update"] = timestamp()
        save(data)
        print(f"[FIND] #{finding['id']}: {finding['type']} at {finding['endpoint']}")

    elif args.endpoint:
        ep = args.endpoint
        if ep not in data["attack_surface"]["endpoints"]:
            data["attack_surface"]["endpoints"].append(ep)
        save(data)
        print(f"[EP] 端点已登记: {ep}")

def cmd_claim(args):
    data = load()
    if not data:
        print("? 蜂巢未初始化")
        return

    if args.agent not in data["agent_states"]:
        data["agent_states"][args.agent] = {"status": "active", "findings": 0, "claimed": [], "last_update": timestamp()}
    data["agent_states"][args.agent]["status"] = "hunting"
    data["agent_states"][args.agent]["last_update"] = timestamp()
    if args.endpoint:
        data["agent_states"][args.agent].setdefault("claimed", []).append(args.endpoint)
    save(data)
    print(f"[CLAIM] {args.agent} -> {args.endpoint or 'general'}")

def cmd_queue(args):
    data = load()
    if not data:
        print("? 蜂巢未初始化")
        return

    if args.add:
        for a in args.add.split(","):
            a = a.strip()
            if a not in data["agent_queue"] and a not in data["completed_agents"]:
                data["agent_queue"].append(a)
                print(f"📋 入队: {a}")
    elif args.remove:
        for a in args.remove.split(","):
            a = a.strip()
            if a in data["agent_queue"]:
                data["agent_queue"].remove(a)
                print(f"🗑️ 出队: {a}")
    elif args.done:
        a = args.done.strip()
        if a in data["agent_queue"]:
            data["agent_queue"].remove(a)
        if a not in data["completed_agents"]:
            data["completed_agents"].append(a)
        if a in data["agent_states"]:
            data["agent_states"][a]["status"] = "done"
        save(data)
        print(f"? {a} 已完成")
        return

    # Show queue
    if data["agent_queue"]:
        print(f"📋 待命蜂群 ({len(data['agent_queue'])}): {', '.join(data['agent_queue'])}")
    else:
        print("📋 队列为空")

    if data["completed_agents"]:
        print(f"? 已完成 ({len(data['completed_agents'])}): {', '.join(data['completed_agents'])}")

    save(data)

def cmd_status(_args):
    data = load()
    if not data:
        print("🐝 蜂巢未初始化")
        return

    print(f"🐝 ==== 蜂巢状态 ====")
    print(f"🎯 任务: {data['mission'][:80]}")
    print(f"📌 阶段: {data['phase']}")
    print(f"🔗 端点: {len(data['attack_surface']['endpoints'])} | 参数: {len(data['attack_surface']['params'])}")
    print(f"🐛 发现: {len(data['findings'])} 个")
    print(f"🤖 活跃Agent: {sum(1 for s in data['agent_states'].values() if s.get('status') == 'hunting')}")
    print(f"📋 等待队列: {len(data['agent_queue'])} | 已完成: {len(data['completed_agents'])}")
    print()

    if data["findings"]:
        high = [f for f in data["findings"] if f.get("severity") in ("high", "critical")]
        med = [f for f in data["findings"] if f.get("severity") == "medium"]
        low = [f for f in data["findings"] if f.get("severity") in ("low", "info")]
        print(f"  🔴 High/Critical: {len(high)} | 🟡 Medium: {len(med)} | ? Low/Info: {len(low)}")

    if data["agent_states"]:
        print()
        for agent, state in data["agent_states"].items():
            emoji = "🟢" if state["status"] == "hunting" else "⚪" if state["status"] == "done" else "🟡"
            print(f"  {emoji} {agent}: {state['status']} | {state.get('findings', 0)} findings")

def cmd_endpoints(args):
    data = load()
    if not data:
        print("[]")
        return
    if args.add:
        for ep in args.add.split(","):
            ep = ep.strip()
            if ep not in data["attack_surface"]["endpoints"]:
                data["attack_surface"]["endpoints"].append(ep)
        save(data)
    print(json.dumps(data["attack_surface"]["endpoints"], ensure_ascii=False, indent=2))

def cmd_swarm(args):
    agents = [a.strip() for a in args.agents.split(",")]
    target = args.target or "unspecified"

    valid = [
        "api-hunter", "sql-injector", "xss-hunter", "http-smuggler", "confusion",
        "waf-bypasser", "race-condition", "ad-pwn", "cloud-escape", "mobile-reverser",
        "supply-chain", "web3-auditor", "llm-redteamer", "binary-exploiter",
        "bb-methodologist", "report-humanizer",
        "scout", "dev", "recon", "reporter", "browser", "ops", "researcher", "teacher", "trader",
    ]
    mapped = []
    for a in agents:
        if a in valid:
            mapped.append(a)
        else:
            for v in valid:
                if a.lower() in v.lower():
                    mapped.append(v)
                    break
            else:
                print(f"?️ 未知Agent: {a} | 可简写: sql=sql-injector xss=xss-hunter api=api-hunter waf=waf-bypasser race=race-condition smug=confusion=")
                print(f"完整列表: {', '.join(sorted(valid))}")
                return

    # Init hive
    subprocess.run([sys.executable, HIVE_FILE, "init", target], capture_output=True)
    for a in mapped:
        subprocess.run([sys.executable, HIVE_FILE, "queue", "--add", a], capture_output=True)

    print(f"?️ 现场组队: {len(mapped)} Agent → {target}")
    print(f"🤖 成员: {', '.join(mapped)}")
    print("")
    print(f"蜂巢已就绪。下一步:")
    for i, a in enumerate(mapped, 1):
        print(f"  {i}. python {HIVE_AGENT} start {a}")

    dispatch = {
        "mode": "swarm",
        "type": "adhoc",
        "label": f"⚔️ 现场组队: {len(mapped)} Agent",
        "agents": mapped,
        "target": target,
    }
    (DATA / "hive-dispatch.json").write_text(
        json.dumps(dispatch, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "current-match.json").write_text(json.dumps({
        "mode": "swarm", "agents": mapped, "is_security": True,
        "hive_active": True, "type": "adhoc",
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_presets(args):
    PRESETS_FILE = HOME / ".claude/config/swarm-presets.json"
    if not PRESETS_FILE.exists():
        print("? 预设库不存在")
        return

    presets = json.loads(PRESETS_FILE.read_text(encoding="utf-8"))["presets"]

    if args.use:
        name = args.use
        preset = presets.get(name)
        if not preset:
            print(f"? 无此预设: {name}")
            print(f"可用: {', '.join(presets.keys())}")
            return
        target = args.target or "unspecified"
        agents = preset["agents"]
        subprocess.run([sys.executable, HIVE_FILE, "init", target], capture_output=True)
        for a in agents:
            subprocess.run([sys.executable, HIVE_FILE, "queue", "--add", a], capture_output=True)
        print(f"{preset['label']} | {len(agents)} Agent ? {target}")
        print(f"🤖 成员: {', '.join(agents)}")
        dispatch = {
            "mode": "swarm", "type": "preset", "preset": name,
            "label": preset["label"], "agents": agents, "target": target,
        }
        (DATA / "hive-dispatch.json").write_text(
            json.dumps(dispatch, ensure_ascii=False, indent=2), encoding="utf-8")
        (DATA / "current-match.json").write_text(json.dumps({
            "mode": "swarm", "agents": agents, "is_security": True, "hive_active": True,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    # List all presets
    print(f"📚 蜂群预设库 ({len(presets)} 套组合):\n")
    for name, cfg in sorted(presets.items()):
        print(f"  {cfg['label']}")
        print(f"    预设名: {name}  |  {len(cfg['agents'])} Agent: {', '.join(cfg['agents'])}")
        print(f"    触发: {' / '.join(cfg['trigger'][:2])[:80]}")
        if cfg.get("note"):
            print(f"    说明: {cfg['note']}")
        print()


# ─── 主入口 ───

if __name__ == "__main__":
    # 全局常量（延迟定义）
    SEC_AGENTS = {
        "api-hunter", "sql-injector", "xss-hunter", "http-smuggler", "confusion",
        "waf-bypasser", "race-condition", "ad-pwn", "cloud-escape", "mobile-reverser",
        "supply-chain", "web3-auditor", "llm-redteamer", "binary-exploiter",
        "bb-methodologist", "report-humanizer",
    }
    PI_AGENTS = {"scout", "dev", "recon", "reporter", "browser", "ops", "researcher", "teacher", "trader"}

    p = argparse.ArgumentParser(description="蜂巢共享大脑")
    sub = p.add_subparsers(dest="cmd")

    i = sub.add_parser("init")
    i.add_argument("target")

    sub.add_parser("read")

    w = sub.add_parser("write")
    w.add_argument("agent")
    w.add_argument("--finding", action="store_true")
    w.add_argument("--type")
    w.add_argument("--severity")
    w.add_argument("--endpoint")
    w.add_argument("--detail")
    w.add_argument("--payload")

    c = sub.add_parser("claim")
    c.add_argument("agent")
    c.add_argument("endpoint", nargs="?")

    q = sub.add_parser("queue")
    q.add_argument("--add")
    q.add_argument("--remove")
    q.add_argument("--done")

    sub.add_parser("status")

    e = sub.add_parser("endpoints")
    e.add_argument("--add")

    s = sub.add_parser("swarm")
    s.add_argument("--agents", required=True, help="逗号分隔: api-hunter,sql-injector,xss-hunter")
    s.add_argument("--target", help="目标URL/描述")

    pr = sub.add_parser("presets")
    pr.add_argument("--use", help="预设名")
    pr.add_argument("--target")

    args = p.parse_args()

    if args.cmd == "init":
        cmd_init(args)
    elif args.cmd == "read":
        cmd_read(args)
    elif args.cmd == "write":
        cmd_write(args)
    elif args.cmd == "claim":
        cmd_claim(args)
    elif args.cmd == "queue":
        cmd_queue(args)
    elif args.cmd == "status":
        cmd_status(args)
    elif args.cmd == "endpoints":
        cmd_endpoints(args)
    elif args.cmd == "swarm":
        cmd_swarm(args)
    elif args.cmd == "presets":
        cmd_presets(args)
    else:
        cmd_status(args)
