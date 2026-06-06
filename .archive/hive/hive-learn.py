#!/usr/bin/env python3
"""
hive-learn.py — Agent 自学引擎 + 全自动管线
新 skill/agent/项目 → 自学提取能力 → 自动更新全部配置

自动更新目标:
  1. learned-agents.json       (注册新Agent)
  2. swarm-presets.json        (自动生成组合技预设)
  3. agent-skill-matrix.json   (更新Agent-Skill映射)
  4. hive-dispatcher rules     (更新匹配规则)
  5. hive-brain 知识地图       (更新技术栈提示)

用法:
  python hive-learn.py --skill ~/.claude/skills/new-tool
  python hive-learn.py --project ~/practice/new-repo
  python hive-learn.py --agent ~/.claude/agents/new-agent.md
  python hive-learn.py --chain "XSS -> CSRF -> ATO"
  python hive-learn.py --sync    (全量重扫所有skill/agent 更新全部配置)
  python hive-learn.py --list
"""
import json, re, sys, os, argparse, subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
HOME = Path.home()
REGISTRY = HOME / ".claude/data/learned-agents.json"
SWARM_PRESETS = HOME / ".claude/config/swarm-presets.json"
AGENT_MATRIX = HOME / ".claude/config/agent-skill-matrix.json"
DISPATCHER = HOME / ".claude/scripts/hive-dispatcher.py"
DATA = HOME / ".claude/data"
SKILLS_DIR = HOME / ".claude/skills"
AGENTS_DIR = HOME / ".claude/agents"
DATA.mkdir(parents=True, exist_ok=True)

AGENT_NAME_MAP = {
    "injection": "sql-injector", "sql": "sql-injector", "sqli": "sql-injector",
    "xss": "xss-hunter", "client-side": "xss-hunter", "dom": "xss-hunter",
    "api": "api-hunter", "graphql": "api-hunter", "jwt": "api-hunter", "idor": "api-hunter",
    "smuggl": "http-smuggler", "desync": "http-smuggler", "http/2": "http-smuggler",
    "waf": "waf-bypasser", "bypass": "waf-bypasser", "firewall": "waf-bypasser",
    "ssrf": "confusion", "path-traversal": "confusion", "host-header": "confusion",
    "race": "race-condition", "toctou": "race-condition", "concurrent": "race-condition",
    "supply-chain": "supply-chain", "npm": "supply-chain", "pypi": "supply-chain", "dependency": "supply-chain",
    "deseriali": "binary-exploiter", "rce": "binary-exploiter", "buffer-overflow": "binary-exploiter",
    "cloud": "cloud-escape", "aws": "cloud-escape", "k8s": "cloud-escape", "docker": "cloud-escape",
    "mobile": "mobile-reverser", "android": "mobile-reverser", "ios": "mobile-reverser",
    "web3": "web3-auditor", "solidity": "web3-auditor", "smart-contract": "web3-auditor",
    "llm": "llm-redteamer", "ai": "llm-redteamer", "prompt-injection": "llm-redteamer",
    "ad": "ad-pwn", "active-directory": "ad-pwn", "kerberos": "ad-pwn",
    "bounty": "bb-methodologist", "recon": "bb-methodologist", "methodology": "bb-methodologist",
    "binary": "binary-exploiter", "reverse-engineering": "binary-exploiter",
    "privilege-escalation": "api-hunter", "account-takeover": "api-hunter", "ato": "api-hunter",
    "data-exfiltration": "sql-injector", "data-leak": "api-hunter",
    "cache-poisoning": "http-smuggler", "web-cache": "http-smuggler",
    "session-hijacking": "api-hunter", "session-fixation": "api-hunter",
    "source-code-disclosure": "confusion", "hardcoded-secret": "api-hunter",
    "credential-theft": "cloud-escape", "metadata": "cloud-escape",
    "open-redirect": "confusion", "redirect": "confusion",
    "subdomain-takeover": "bb-methodologist", "dangling-dns": "bb-methodologist",
    "prototype-pollution": "binary-exploiter", "proto-pollution": "binary-exploiter",
    "idor": "api-hunter", "mass-assignment": "api-hunter",
    "rate-limit": "race-condition", "brute-force": "race-condition",
    "repair": "hive-repair", "fix": "hive-repair", "纠错": "hive-repair", "维修": "hive-repair",
}

def load_json(path):
    if path.exists():
        try: return json.loads(path.read_text(encoding="utf-8"))
        except: pass
    return None

def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def load_registry():
    r = load_json(REGISTRY)
    return r if r else {"agents": {}, "chains": [], "stats": {}, "updated": ""}

def save_registry(reg):
    reg["stats"] = {"agents": len(reg.get("agents",{})), "chains": len(reg.get("chains",[])), "presets": len(reg.get("presets",{}))}
    reg["updated"] = datetime.now(TZ).isoformat()
    save_json(REGISTRY, reg)

def extract_capabilities(text):
    caps = {"keywords": [], "tools": [], "vuln_types": [], "agents": []}
    kw_map = {
        "injection": r"injection|sql.*injection|sqli|命令注入|command.*inject",
        "xss": r"xss|cross.*site.*script|反射.*xss|存储.*xss|dom.*xss",
        "ssrf": r"ssrf|server.*side.*request.*forger",
        "csrf": r"csrf|cross.*site.*request",
        "idor": r"idor|insecure.*direct.*object|越权|未授权.*访问",
        "jwt": r"jwt|json.*web.*token",
        "graphql": r"graphql",
        "path-traversal": r"path.*traversal|目录.*遍历|路径.*穿越",
        "file-upload": r"file.*upload|文件.*上传",
        "xxe": r"xxe|xml.*external.*entit",
        "ssti": r"ssti|server.*side.*template.*inject",
        "smuggling": r"smuggl|desync|http.*走私|请求.*走私",
        "deserialization": r"deserializ|反序列化|unserializ",
        "waf-bypass": r"waf.*绕过|bypass.*waf|防火墙.*绕过",
        "race-condition": r"race.*condition|竞态|toctou",
        "cloud": r"cloud|aws|azure|gcp|云.*安全|容器.*逃逸",
        "crypto": r"crypto|加密|密码|哈希|aes|rsa|sha",
        "auth": r"auth|认证|登录|token|session|oauth|saml",
        "business-logic": r"business.*logic|业务.*逻辑|流程.*绕过",
        "repair": r"repair|fuck|纠错|fix.*command|修正命令",
    }
    for name, pat in kw_map.items():
        if re.search(pat, text, re.IGNORECASE):
            caps["vuln_types"].append(name)
            matched = AGENT_NAME_MAP.get(name)
            if matched and matched not in caps["agents"]:
                caps["agents"].append(matched)
    tools = re.findall(r'(sqlmap|burp|nmap|ffuf|nuclei|subfinder|httpx|ghidra|ida|pwntools|frida|jadx|metasploit|semgrep|codeql|dalfox|xsstrike)', text, re.IGNORECASE)
    caps["tools"] = list(set(t.lower() for t in tools))
    return caps

def learn_skill(skill_path):
    path = Path(os.path.expanduser(skill_path))
    if not path.exists(): return {"error": f"Path not found: {skill_path}"}
    skill_md = path / "SKILL.md"
    if not skill_md.exists(): return {"error": f"No SKILL.md in {skill_path}"}
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    caps = extract_capabilities(text)
    caps["name"] = path.name; caps["source"] = str(path); caps["type"] = "skill"
    caps["learned_at"] = datetime.now(TZ).isoformat()
    if not caps["agents"]: caps["agents"] = ["api-hunter"]
    return caps

def learn_project(project_path):
    path = Path(os.path.expanduser(project_path))
    if not path.exists(): return {"error": f"Path not found: {project_path}"}
    readme = path / "README.md"
    text = readme.read_text(encoding="utf-8", errors="replace") if readme.exists() else ""
    caps = extract_capabilities(text)
    caps["name"] = path.name; caps["source"] = str(path); caps["type"] = "project"
    caps["learned_at"] = datetime.now(TZ).isoformat()
    tech = []
    if (path / "package.json").exists(): tech.append("node.js")
    if (path / "requirements.txt").exists(): tech.append("python")
    if (path / "Cargo.toml").exists(): tech.append("rust")
    if (path / "go.mod").exists(): tech.append("go")
    if (path / "Dockerfile").exists(): tech.append("docker")
    caps["tech_stack"] = tech
    if not caps["agents"]:
        caps["agents"] = list(set(AGENT_NAME_MAP.get(t, "api-hunter") for t in tech))
    return caps

def learn_agent(agent_path):
    path = Path(os.path.expanduser(agent_path))
    if not path.exists(): return {"error": f"Agent not found: {agent_path}"}
    text = path.read_text(encoding="utf-8", errors="replace")
    caps = extract_capabilities(text)
    caps["name"] = path.stem; caps["source"] = str(path); caps["type"] = "agent"
    caps["learned_at"] = datetime.now(TZ).isoformat()
    title = re.search(r"#\s*(.+)", text)
    caps["title"] = title.group(1) if title else path.stem
    if not caps["agents"]: caps["agents"] = [path.stem]
    return caps

def learn_hackerone_chain(chain_desc):
    steps = [s.strip() for s in re.split(r'->|→|>|->>|=>', chain_desc)]
    agents = []
    for step in steps:
        norm = step.lower().replace(" ", "-").replace("_", "-")
        for name, agent in AGENT_NAME_MAP.items():
            if name in norm and agent not in agents:
                agents.append(agent); break
        else:
            for name, agent in AGENT_NAME_MAP.items():
                if any(kw in norm for kw in name.split("-")) and agent not in agents:
                    agents.append(agent); break
    if len(agents) < 2: return {"error": f"Need 2+ types, found: {agents}"}
    chain_id = re.sub(r'[^a-z0-9_]', '_', chain_desc.lower())[:40]
    return {
        "preset_name": f"chain_{chain_id}",
        "agents": agents,
        "label": f"Chain: {' -> '.join(steps[:4])}",
        "preset": {
            "name": f"chain_{chain_id}",
            "trigger": [f"({chain_desc.lower()[:60]})"],
            "trigger_score": 10,
            "agents": agents,
            "label": f"Chain: {' -> '.join(steps[:4])}",
            "recon_first": True,
            "note": f"H1 chain: {chain_desc} | {len(agents)} agents",
        }
    }

# ═══════════════════════════════════════════════════
# 全自动更新管线
# ═══════════════════════════════════════════════════

def update_swarm_presets(agents, name, label, note=""):
    """自动在swarm-presets.json生成新组合技"""
    presets = load_json(SWARM_PRESETS) or {"presets": {}}
    preset_name = re.sub(r'[^a-z0-9_]', '_', name.lower())[:40]
    if preset_name in presets["presets"]:
        return f"preset '{preset_name}' already exists"
    key_triggers = "|".join(agents[:3])
    presets["presets"][preset_name] = {
        "trigger": [f"({name}|{key_triggers})"],
        "trigger_score": 7,
        "agents": agents,
        "label": label,
        "recon_first": True,
        "note": note or f"Auto-generated from {name} | {len(agents)} agents",
    }
    save_json(SWARM_PRESETS, presets)
    return f"Added preset '{preset_name}': {', '.join(agents[:4])}"

def update_agent_matrix(result):
    """更新agent-skill-matrix.json"""
    matrix = load_json(AGENT_MATRIX)
    if not matrix: return "matrix not found"
    name = result["name"]
    agents = result.get("agents", [])
    if "agents" not in matrix: matrix["agents"] = {}
    # 加到 PI agents 或 audit sub_agents
    target = "audit" if result["type"] in ("agent", "skill") else "dev"
    if target in matrix.get("agents", {}):
        existing = matrix["agents"][target].get("sub_agents", [])
        for a in agents:
            if a not in existing and a not in matrix["agents"][target].get("skills", []):
                existing.append(a)
        matrix["agents"][target]["sub_agents"] = existing
    save_json(AGENT_MATRIX, matrix)
    return f"Matrix updated: {target} -> +{len(agents)} agents"

def add_dispatcher_rule(agents, name):
    """在hive-dispatcher SEC_SOLO_RULES追加匹配规则"""
    if not DISPATCHER.exists(): return "dispatcher not found"
    lines = DISPATCHER.read_text(encoding="utf-8").split("\n")
    keywords = re.sub(r'[-_]', ' ', name).strip()[:30]
    # 找最后一个 SEC_SOLO_RULES 规则位置
    last_rule_line = -1
    for i, line in enumerate(lines):
        if 'r"' in line and 'SEC_SOLO_RULES' in lines[max(0,i-5):i+1]:
            continue
        if '(r"' in line and any(a in line for a in agents):
            last_rule_line = -2  # already exists
            break
        if '(r"' in line: last_rule_line = i
    if last_rule_line == -2: return "rule already exists"
    if last_rule_line < 0: return "no insertion point"
    rule = f'    (r"{keywords}|{name[:20]}", "{agents[0]}", 9),'
    lines.insert(last_rule_line + 1, rule)
    DISPATCHER.write_text("\n".join(lines), encoding="utf-8")
    return f"Added dispatcher rule for {agents[0]}"

def sync_all():
    """全量扫描: 所有skill + 所有agent → 重建全部配置"""
    results = []
    # 扫描 agents/
    if AGENTS_DIR.exists():
        for f in sorted(AGENTS_DIR.glob("*.md")):
            r = learn_agent(str(f))
            if "error" not in r: results.append(r)
    # 扫描 skills/ (top-level, skip communitytools/plugin dirs)
    if SKILLS_DIR.exists():
        for d in sorted(SKILLS_DIR.iterdir()):
            if d.is_dir() and (d / "SKILL.md").exists():
                r = learn_skill(str(d))
                if "error" not in r: results.append(r)

    # 收集所有 agent
    all_agents = set()
    for r in results:
        for a in r.get("agents", []): all_agents.add(a)

    # 更新全部配置
    reg = load_registry()
    for r in results:
        reg["agents"][r["name"]] = r
        if len(r.get("agents", [])) >= 2:
            update_swarm_presets(r["agents"], r["name"], f"Auto: {r['name']}", f"Auto from {r['type']}")

    # 生成 apocalypse 全Agent预设
    apocalypse = sorted(all_agents)
    presets = load_json(SWARM_PRESETS) or {"presets": {}}
    if "apocalypse" not in presets.get("presets", {}):
        presets["presets"] = presets.get("presets", {})
        presets["presets"]["apocalypse"] = {
            "trigger": ["(末日|火力全开|全部拉|倾巢|apocalypse)"],
            "trigger_score": 11,
            "agents": apocalypse,
            "label": f"[AUTO] 全火力 {len(apocalypse)} Agent",
            "recon_first": True,
            "note": f"Auto-generated by sync | {len(apocalypse)} agents",
        }
    save_json(SWARM_PRESETS, presets)

    reg["presets"] = {k: v for k, v in presets.get("presets", {}).items()}
    save_registry(reg)

    print(f"[SYNC] Scanned {len(results)} items | {len(all_agents)} unique agents | {len(presets['presets'])} presets")
    return results

# ═══════════════════════════════════════════════════
# Commands
# ═══════════════════════════════════════════════════

def cmd_learn(args):
    if args.skill: result = learn_skill(args.skill)
    elif args.project: result = learn_project(args.project)
    elif args.agent: result = learn_agent(args.agent)
    else: print("Use --skill/--project/--agent"); return
    if "error" in result: print(f"ERROR: {result['error']}"); return

    reg = load_registry()
    reg["agents"][result["name"]] = result
    save_registry(reg)
    print(f"[LEARNED] {result['name']} ({result['type']}) | Agents: {result.get('agents',[])}")

    # 全自动更新管线
    if len(result["agents"]) >= 2:
        p = update_swarm_presets(result["agents"], result["name"], f"Auto: {result['name']}")
        print(f"  [PRESETS] {p}")
    m = update_agent_matrix(result)
    print(f"  [MATRIX] {m}")
    d = add_dispatcher_rule(result["agents"], result["name"])
    print(f"  [DISPATCH] {d}")

def cmd_chain(args):
    result = learn_hackerone_chain(args.chain)
    if "error" in result: print(f"ERROR: {result['error']}"); return
    print(f"[CHAIN] {result['label']} | Agents: {result['agents']}")
    update_swarm_presets(result["agents"], result["preset_name"], result["label"])
    reg = load_registry()
    reg["chains"].append({"desc": args.chain, "agents": result["agents"], "added": datetime.now(TZ).isoformat()})
    save_registry(reg)
    print(f"  [AUTO] Added to presets + registry")

def cmd_list(args):
    reg = load_registry()
    if not reg["agents"] and not reg["chains"]: print("Empty. Run --sync or --skill first."); return
    print(f"[REGISTRY] {reg['stats']}")
    print(f"  Agents: {len(reg['agents'])} | Chains: {len(reg['chains'])}")
    for n, i in sorted(reg["agents"].items()):
        print(f"  {n} ({i['type']}) -> {i.get('agents',[])}")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--skill"); p.add_argument("--project"); p.add_argument("--agent")
    p.add_argument("--list", action="store_true")
    p.add_argument("--chain")
    p.add_argument("--sync", action="store_true")
    args = p.parse_args()

    if args.sync:
        sync_all()
    elif args.list:
        cmd_list(args)
    elif args.chain:
        cmd_chain(args)
    elif args.skill or args.project or args.agent:
        cmd_learn(args)
    else:
        prs = load_json(SWARM_PRESETS)
        print(f"HiveLearn 就绪 | {len(prs.get('presets',{}))} presets")
        print("  --skill/--project/--agent  → 学一个")
        print("  --chain 'XSS -> CSRF -> ATO' → H1链")
        print("  --sync → 全量扫描重建全部配置")
        print("  --list → 看学了什么")
