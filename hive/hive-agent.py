#!/usr/bin/env python3
"""
hive-agent.py — 蜂群Agent执行器
每个安全Agent启动/执行/完成时自动调此脚本，维护蜂巢共享状态。

启动时:
  python hive-agent.py start xss-hunter https://example.com/search
  → 从hive-mind读攻击面上下文 → 输出给Agent的briefing

发现时:
  python hive-agent.py report xss-hunter --type reflected-xss --sev high --ep /search --detail "q param no escaping"

完成时:
  python hive-agent.py done xss-hunter
  → 标记完成，看队列是否还有 → 有则建议下一个Agent
"""
import json, sys, argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
HOME = Path.home()
HIVE = HOME / ".claude/data/hive-mind.json"
HIVE_CMD = str(HOME / ".claude/scripts/hive-mind.py")
DISPATCH = HOME / ".claude/data/hive-dispatch.json"

AGENT_INFO = {
    "api-hunter":       {"focus": "API端点/JWT/权限/越权", "tools": "curl, Burp, api-probe.py"},
    "sql-injector":     {"focus": "SQL注入全谱", "tools": "sqlmap, Ghauri, 手工payload"},
    "xss-hunter":       {"focus": "XSS/CSP绕过/PostMessage", "tools": "XSStrike, dalfox, 手工payload"},
    "http-smuggler":    {"focus": "HTTP走私/去同步", "tools": "smuggler-probe.py, Burp Turbo Intruder"},
    "confusion":        {"focus": "路径穿越/SSRF/Host Header混淆", "tools": "Burp, python fuzzer"},
    "waf-bypasser":     {"focus": "WAF识别和绕过", "tools": "wafw00f, sqlmap tamper, ffuf"},
    "race-condition":   {"focus": "竞态/TOCTOU/并发利用", "tools": "Turbo Intruder, asyncio脚本"},
    "ad-pwn":           {"focus": "AD域/Kerberos/ADCS", "tools": "BloodHound, Impacket, Mimikatz"},
    "cloud-escape":     {"focus": "容器逃逸/K8s/云凭据", "tools": "cdk, kube-hunter, ScoutSuite"},
    "mobile-reverser":  {"focus": "Android/iOS逆向", "tools": "Frida, Ghidra, jadx, objection"},
    "supply-chain":     {"focus": "供应链/npm/PyPI/CI-CD", "tools": "npm audit, pip-audit, semgrep"},
    "web3-auditor":     {"focus": "智能合约/DeFi", "tools": "Slither, Echidna, Foundry"},
    "llm-redteamer":    {"focus": "Prompt Injection/RAG/Agent安全", "tools": "Garak, promptfoo"},
    "binary-exploiter": {"focus": "二进制/ROP/堆利用", "tools": "pwntools, Ghidra, GDB+pwndbg"},
    "bb-methodologist": {"focus": "赏金方法论/侦察/流程", "tools": "subfinder, httpx, nuclei"},
    "report-humanizer": {"focus": "去AI味/报告润色", "tools": "humanizer-zh skill"},
}

def timestamp():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

def load_hive():
    if HIVE.exists():
        return json.loads(HIVE.read_text(encoding="utf-8"))
    return None

def save_hive(data):
    data["_updated"] = timestamp()
    HIVE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def load_dispatch():
    if DISPATCH.exists():
        return json.loads(DISPATCH.read_text(encoding="utf-8"))
    return None

# ─── 命令 ───

def cmd_start(agent, target_url=None):
    """Agent启动 → 读蜂巢上下文 → 输出briefing"""
    hive = load_hive()
    dispatch = load_dispatch()
    info = AGENT_INFO.get(agent, {"focus": "通用安全", "tools": "通用"})

    briefing = {
        "agent": agent,
        "focus": info["focus"],
        "tools": info["tools"],
        "ts": timestamp(),
    }

    if hive:
        briefing["mission"] = hive.get("mission", "")
        briefing["phase"] = hive.get("phase", "")
        briefing["known_endpoints"] = hive["attack_surface"].get("endpoints", [])
        briefing["known_params"] = hive["attack_surface"].get("params", [])
        briefing["tech_stack"] = hive["attack_surface"].get("tech_stack", [])
        briefing["waf"] = hive["attack_surface"].get("waf")

        # 告诉Agent：其他Agent已经发现了什么（避免重复）
        other_findings = [f for f in hive.get("findings", []) if f.get("agent") != agent]
        briefing["other_findings_count"] = len(other_findings)

        # 分配端点（防止撞车）
        unclaimed = [ep for ep in hive["attack_surface"].get("endpoints", [])]
        for s in hive.get("agent_states", {}).values():
            for ep in s.get("claimed", []):
                if ep in unclaimed:
                    unclaimed.remove(ep)
        briefing["suggested_targets"] = unclaimed[:5] if target_url is None else [target_url]

        # 标记Agent已激活
        if agent not in hive["agent_states"]:
            hive["agent_states"][agent] = {"status": "hunting", "findings": 0, "claimed": [], "last_update": timestamp()}
        hive["agent_states"][agent]["status"] = "hunting"
        hive["agent_states"][agent]["last_update"] = timestamp()
        if target_url:
            hive["agent_states"][agent].setdefault("claimed", []).append(target_url)
        save_hive(hive)

    # 输出briefing → stdout → 主模型读取
    print(json.dumps(briefing, ensure_ascii=False, indent=2))

    # 蜂群模式下提示协作状态
    if dispatch and dispatch.get("mode") == "swarm":
        agents = dispatch.get("agents", [])
        others = [a for a in agents if a != agent]
        if others:
            print(f"\n🕷️ 你并非孤军。队友也在工作: {', '.join(others)}")
            print(f"🧠 所有发现汇总在 hive-mind ← python {HIVE_CMD} read")


def cmd_report(agent, args):
    """Agent发现漏洞 → 写回蜂巢"""
    hive = load_hive()
    if not hive:
        print("❌ 蜂巢未初始化")
        return

    import subprocess

    finding = {
        "id": f"{agent}-{len(hive['findings'])+1}",
        "agent": agent,
        "type": args.type or "info",
        "severity": args.severity or "info",
        "endpoint": args.endpoint or "",
        "detail": args.detail or "",
        "payload": args.payload or "",
        "confirmed": False,
        "ts": timestamp(),
    }
    hive["findings"].append(finding)

    if agent not in hive["agent_states"]:
        hive["agent_states"][agent] = {"status": "hunting", "findings": 0, "claimed": [], "last_update": timestamp()}
    hive["agent_states"][agent]["findings"] += 1
    hive["agent_states"][agent]["last_update"] = timestamp()

    severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵", "info": "⚪"}
    sev = severity_emoji.get(args.severity, "⚪")
    print(f"{sev} {agent} 发现: {args.type} @ {args.endpoint} | {args.detail[:60]}")

    save_hive(hive)

    # 关键发现通知所有活跃Agent
    if args.severity in ("high", "critical"):
        print(f"📢 高严重度发现！建议所有活跃Agent检查相关攻击面。")


def cmd_done(agent):
    """Agent完成 → 标记done → 看队列是否有下一个"""
    import subprocess

    # 标记完成
    r = subprocess.run([sys.executable, HIVE_CMD, "queue", "--done", agent],
                       capture_output=True, text=True, encoding="utf-8")
    print(r.stdout.strip())

    # 检查队列
    hive = load_hive()
    if hive and hive.get("agent_queue"):
        next_agent = hive["agent_queue"][0]
        info = AGENT_INFO.get(next_agent, {"focus": "通用"})
        print(f"\n📋 下一个待命: {next_agent} ({info['focus']})")
        print(f"   python {__file__} start {next_agent}")
    else:
        # 全部完成 → 汇总
        findings = hive.get("findings", [])
        if findings:
            high = sum(1 for f in findings if f.get("severity") in ("high", "critical"))
            print(f"\n✅ 蜂群任务完成！{len(findings)} 个发现 ({high} 个高危)")
            print(f"   python {HIVE_CMD} status  ← 查看全景")
        else:
            print(f"\n✅ 蜂群任务完成！未发现高危漏洞。")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="蜂群Agent执行器")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("start")
    s.add_argument("agent")
    s.add_argument("target", nargs="?")

    r = sub.add_parser("report")
    r.add_argument("agent")
    r.add_argument("--type")
    r.add_argument("--severity", "--sev")
    r.add_argument("--endpoint", "--ep")
    r.add_argument("--detail")
    r.add_argument("--payload")

    d = sub.add_parser("done")
    d.add_argument("agent")

    args = p.parse_args()

    import subprocess as sp

    if args.cmd == "start":
        cmd_start(args.agent, args.target)
    elif args.cmd == "report":
        cmd_report(args.agent, args)
    elif args.cmd == "done":
        cmd_done(args.agent)
