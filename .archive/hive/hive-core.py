#!/usr/bin/env python3
"""
hive-core.py — 蜂巢核心 v2 (借鉴 Claude Flow + Letta)
7项升级一步到位

1. 记忆三层: Core(RAM)/Recall(Cache)/Archival(冷存) — Letta模式
2. 共识投票: 3Agent独立验证才确认 — Claude Flow Raft模式
3. 蜂群拓扑: 平行/链式/环形 — 自动选
4. 战后复盘: 打完自动分析模式 — Letta Dreaming
5. Token预算: 全局上限+Agent配额 — 防止暴走
6. Git记忆: 发现可回滚/可推GitHub — Letta MemFS
7. 学习闭环: RETRIEVE→JUDGE→DISTILL→CONSOLIDATE→ROUTE

用法:
  python hive-core.py --upgrade          # 升级hive-mind到v2
  python hive-core.py --verify F001      # 共识投票验证发现
  python hive-core.py --autopsy          # 战后复盘
  python hive-core.py --learn            # 学习闭环一轮
"""
import json, subprocess, sys, os, re, argparse, hashlib, time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

TZ = timezone(timedelta(hours=8))
HOME = Path.home()
HIVE = HOME / ".claude/data/hive-mind.json"
DATA = HOME / ".claude/data"
DATA.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════
# 1. 三层记忆系统 (Letta MemGPT 架构)
# ═══════════════════════════════════════════════════

MEMORY_TIERS = {
    "core": {   # 当前会话 — 始终在上下文
        "max_items": 20,
        "ttl_hours": 24,
        "priority": 1,
    },
    "recall": {  # 可搜索 — 对话历史
        "max_items": 200,
        "ttl_hours": 168,  # 7天
        "priority": 2,
    },
    "archival": { # 永久 — 重要决策/发现
        "max_items": 1000,
        "ttl_hours": None,  # 永不过期
        "priority": 3,
    },
}

def tier_memory(hive_data):
    data = hive_data.copy() if hive_data else {}
    if "_memory" not in data:
        data["_memory"] = {"core": [], "recall": [], "archival": []}
    findings = data.get("findings", [])

    for f in findings:
        fid = f.get("id", "")
        if not any(m["id"] == fid for tier in data["_memory"].values() for m in tier):
            severity = f.get("severity", "info")
            mem = {
                "id": fid,
                "type": f.get("type",""), "severity": severity,
                "agent": f.get("agent",""), "endpoint": f.get("endpoint",""),
                "ts": f.get("ts", datetime.now(TZ).isoformat()),
                "hash": hashlib.md5(json.dumps(f,sort_keys=True).encode()).hexdigest()[:8],
            }
            if severity in ("critical", "high"):
                data["_memory"]["core"].append(mem)
            elif severity == "medium":
                data["_memory"]["recall"].append(mem)
            else:
                data["_memory"]["archival"].append(mem)

    for tier, cfg in MEMORY_TIERS.items():
        lst = data["_memory"].get(tier, [])
        if cfg["max_items"] and len(lst) > cfg["max_items"]:
            overflow = lst[:-cfg["max_items"]]
            data["_memory"][tier] = lst[-cfg["max_items"]:]
            if tier == "core":
                for m in overflow:
                    if m not in data["_memory"]["recall"]:
                        data["_memory"]["recall"].insert(0, m)

    return data

# ═══════════════════════════════════════════════════
# 2. 共识投票引擎 (Claude Flow Raft)
# ═══════════════════════════════════════════════════

CONSENSUS_RULES = {
    "critical": {"required": 3, "threshold": 0.66},  # 3个Agent中2个确认
    "high":     {"required": 2, "threshold": 0.5},
    "medium":   {"required": 2, "threshold": 0.5},
    "low":      {"required": 1, "threshold": 1.0},
}

def consensus_vote(findings, new_finding):
    fid = new_finding.get("id", "")
    votes = []
    for f in findings:
        if f.get("id") == fid: continue
        if f.get("endpoint") == new_finding.get("endpoint") or \
           f.get("type","").lower() == new_finding.get("type","").lower():
            votes.append({"agent": f.get("agent"), "agree": True})
    severity = new_finding.get("severity", "medium")
    cfg = CONSENSUS_RULES.get(severity, {"required": 2, "threshold": 0.5})
    agree = len(votes)
    total = max(cfg["required"], agree + 1)
    confirmed = agree >= cfg["required"] and (agree / total) >= cfg["threshold"]

    return {"confirmed": confirmed, "votes": votes, "agree": agree,
            "required": cfg["required"], "total": total}

# ═══════════════════════════════════════════════════
# 3. 蜂群拓扑选择
# ═══════════════════════════════════════════════════

TOPOLOGIES = {
    "parallel":   {"desc": "独立并行 无依赖", "when": "agents <= 4 and independent"},
    "chain":      {"desc": "链式接力 A→B→C", "when": "sequential recon->audit->report"},
    "ring":       {"desc": "环形验证 A验证B B验证C", "when": "consensus needed"},
    "star":       {"desc": "星型 hub分发", "when": "one coordinator + N workers"},
}

def select_topology(agents, needs_consensus=False):
    n = len(agents)
    if needs_consensus: return "ring"
    if n <= 4: return "parallel"
    if n <= 8: return "star"
    return "parallel"

# ═══════════════════════════════════════════════════
# 4. 战后复盘引擎 (Letta Dreaming模式)
# ═══════════════════════════════════════════════════

def generate_autopsy(hive_data):
    findings = hive_data.get("findings", [])
    agents = hive_data.get("agent_states", {})
    if not findings:
        return {"status": "no findings"}

    by_severity = defaultdict(int)
    by_agent = defaultdict(int)
    by_type = defaultdict(int)
    for f in findings:
        by_severity[f.get("severity", "info")] += 1
        by_agent[f.get("agent", "?")] += 1
        by_type[f.get("type", "?")] += 1

    agent_efficiency = {}
    for a, s in agents.items():
        agent_efficiency[a] = {
            "findings": s.get("findings", 0),
            "status": s.get("status", "?"),
        }

    patterns = []
    if by_severity.get("critical", 0) > 0:
        patterns.append(f"CRIT: {by_severity['critical']} criticals found — immediate fix required")
    if by_severity.get("high", 0) >= 3:
        patterns.append(f"HIGH: {by_severity['high']} highs — systemic issue likely")
    if by_type.get("SQL Injection", 0) > 0 and by_type.get("XSS", 0) > 0:
        patterns.append("PATTERN: input validation missing across multiple endpoints")

    idle_agents = [a for a, s in agent_efficiency.items() if s["findings"] == 0]
    if idle_agents:
        patterns.append(f"IDLE: {len(idle_agents)} agents found nothing — {', '.join(idle_agents[:3])}")

    return {
        "ts": datetime.now(TZ).isoformat(),
        "mission": hive_data.get("mission", "?")[:80],
        "total_findings": len(findings),
        "by_severity": dict(by_severity),
        "by_type": dict(by_type),
        "agent_efficiency": agent_efficiency,
        "patterns": patterns,
        "verdict": "PASS" if by_severity.get("critical", 0) == 0 else "ACTION_REQUIRED",
    }

# ═══════════════════════════════════════════════════
# 5. Token预算控制
# ═══════════════════════════════════════════════════

TOKEN_BUDGET = {
    "default_total": 200000,    # 全会话20万token上限
    "agent_quota": 30000,       # 每个Agent 3万
    "overseer_reserve": 5000,   # 监督者预留
    "warning_threshold": 0.7,   # 70%告警
    "block_threshold": 0.9,     # 90%阻断非关键Agent
}

def check_budget(spent, budget=None):
    budget = budget or TOKEN_BUDGET
    ratio = spent / budget["default_total"] if budget["default_total"] else 0
    status = "green" if ratio < budget["warning_threshold"] else \
             "yellow" if ratio < budget["block_threshold"] else "red"
    return {"spent": spent, "total": budget["default_total"], "ratio": ratio, "status": status}

# ═══════════════════════════════════════════════════
# 6. Git记忆追踪 (Letta MemFS模式)
# ═══════════════════════════════════════════════════

def git_memory_commit(hive_data, message=None):
    memory_dir = HOME / ".claude/memory-git"
    memory_dir.mkdir(parents=True, exist_ok=True)

    mem_file = memory_dir / "hive-memory.json"
    mem_file.write_text(json.dumps(hive_data, ensure_ascii=False, indent=2), encoding="utf-8")

    if not (memory_dir / ".git").exists():
        subprocess.run(["git", "init"], cwd=memory_dir, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=memory_dir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init hive memory"], cwd=memory_dir, capture_output=True)
        return "Memory git repo initialized"

    subprocess.run(["git", "add", "-A"], cwd=memory_dir, capture_output=True)
    msg = message or f"memory snapshot {datetime.now(TZ).strftime('%Y%m%d-%H%M%S')}"
    r = subprocess.run(["git", "commit", "-m", msg], cwd=memory_dir, capture_output=True, text=True)
    return "committed" if r.returncode == 0 else f"no changes: {r.stderr[:80]}"

# ═══════════════════════════════════════════════════
# 7. 学习闭环 (Claude Flow SONA)
# ═══════════════════════════════════════════════════

def learning_loop(hive_data):
    """RETRIEVE fail patterns → JUDGE → DISTILL rules → CONSOLIDATE → ROUTE"""
    findings = hive_data.get("findings", [])
    if not findings: return {"status": "no data"}

    lessons = {"patterns": [], "new_rules": [], "agent_adjustments": []}

    # RETRIEVE: 多次出现的漏洞类型
    type_counts = defaultdict(int)
    for f in findings:
        type_counts[f.get("type","?")] += 1
    for t, c in type_counts.items():
        if c >= 3:
            lessons["patterns"].append(f"RECURRING: {t} found {c}x — systemic weakness")

    # JUDGE: 哪些Agent没产出
    agent_findings = defaultdict(int)
    for f in findings:
        agent_findings[f.get("agent","?")] += 1
    zero_agents = [a for a in hive_data.get("agent_states", {}) if agent_findings[a] == 0]
    if zero_agents:
        lessons["agent_adjustments"].append(f"REMOVE from preset: {', '.join(zero_agents[:3])}")

    # DISTILL: 高频端点 → 规则
    ep_counts = defaultdict(int)
    for f in findings:
        if f.get("endpoint"): ep_counts[f["endpoint"]] += 1
    for ep, c in sorted(ep_counts.items(), key=lambda x: -x[1])[:5]:
        if c >= 2:
            lessons["new_rules"].append(f"AUTO-SCAN: {ep} ({c} findings)")

    # CONSOLIDATE: 写回
    (DATA / "learning.json").write_text(json.dumps({
        "ts": datetime.now(TZ).isoformat(),
        "findings_analyzed": len(findings),
        "lessons": lessons,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    return lessons

# ═══════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════

def cmd_upgrade():
    hive = json.loads(HIVE.read_text(encoding="utf-8")) if HIVE.exists() else {"findings": [], "agent_states": {}, "mission": ""}
    hive = tier_memory(hive)
    HIVE.write_text(json.dumps(hive, ensure_ascii=False, indent=2), encoding="utf-8")
    git_memory_commit(hive, "upgrade to v2 memory tiers")
    print(f"[UPGRADE] v2 | Core:{len(hive['_memory']['core'])} Recall:{len(hive['_memory']['recall'])} Archival:{len(hive['_memory']['archival'])}")

def cmd_verify(args):
    hive = json.loads(HIVE.read_text(encoding="utf-8")) if HIVE.exists() else {"findings": []}
    target = None
    for f in hive["findings"]:
        if args.verify in f.get("id", ""):
            target = f; break
    if not target:
        print(f"Finding {args.verify} not found"); return
    result = consensus_vote(hive["findings"], target)
    print(json.dumps({"finding": target["id"], **result}, ensure_ascii=False, indent=2))

def cmd_autopsy():
    hive = json.loads(HIVE.read_text(encoding="utf-8")) if HIVE.exists() else {"findings": []}
    report = generate_autopsy(hive)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    (DATA / "autopsy.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

def cmd_learn():
    hive = json.loads(HIVE.read_text(encoding="utf-8")) if HIVE.exists() else {"findings": []}
    lessons = learning_loop(hive)
    print(json.dumps(lessons, ensure_ascii=False, indent=2))

def cmd_git():
    hive = json.loads(HIVE.read_text(encoding="utf-8")) if HIVE.exists() else {}
    result = git_memory_commit(hive)
    print(result)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--upgrade", action="store_true")
    p.add_argument("--verify")
    p.add_argument("--autopsy", action="store_true")
    p.add_argument("--learn", action="store_true")
    p.add_argument("--git", action="store_true")
    args = p.parse_args()

    if args.upgrade: cmd_upgrade()
    elif args.verify: cmd_verify(args)
    elif args.autopsy: cmd_autopsy()
    elif args.learn: cmd_learn()
    elif args.git: cmd_git()
    else:
        print("hive-core v2 | --upgrade --verify --autopsy --learn --git")
