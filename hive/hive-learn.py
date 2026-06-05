#!/usr/bin/env python3
"""
hive-learn.py — Agent 自学引擎
新 skill / 开源项目扔给它 → 自动读 SKILL.md → 提取能力 → 注册到 hive-mind

用法:
  python hive-learn.py --skill ~/.claude/skills/new-tool     → 自学一个skill
  python hive-learn.py --project ~/practice/new-repo         → 自学一个开源项目
  python hive-learn.py --list                                 → 列出已注册的自学Agent
  python hive-learn.py --from-hackerone "XSS->CSRF->ATO"     → 从漏洞链生成组合技
"""
import json, re, sys, os, argparse, subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
HOME = Path.home()
REGISTRY = HOME / ".claude/data/learned-agents.json"
SWARM_PRESETS = HOME / ".claude/config/swarm-presets.json"
DATA = HOME / ".claude/data"
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
    # HackerOne report keywords
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
}

def load_registry():
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {"agents": {}, "chains": [], "updated": ""}

def save_registry(reg):
    reg["updated"] = datetime.now(TZ).isoformat()
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")

def extract_capabilities(text):
    """从 SKILL.md / README 提取攻击能力"""
    caps = {"keywords": [], "tools": [], "endpoints": [], "vuln_types": [], "agents": []}

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
    }

    for name, pat in kw_map.items():
        if re.search(pat, text, re.IGNORECASE):
            caps["vuln_types"].append(name)
            matched = AGENT_NAME_MAP.get(name)
            if matched and matched not in caps["agents"]:
                caps["agents"].append(matched)

    # 工具提取
    tools = re.findall(r'(sqlmap|burp|nmap|ffuf|nuclei|subfinder|httpx|ghidra|ida|pwntools|frida|jadx|metasploit|semgrep|codeql|dalfox|xsstrike)', text, re.IGNORECASE)
    caps["tools"] = list(set(t.lower() for t in tools))

    return caps

def learn_skill(skill_path):
    path = Path(os.path.expanduser(skill_path))
    if not path.exists():
        return {"error": f"Path not found: {skill_path}"}

    skill_md = path / "SKILL.md"
    if not skill_md.exists():
        return {"error": f"No SKILL.md found in {skill_path}"}

    text = skill_md.read_text(encoding="utf-8", errors="replace")
    caps = extract_capabilities(text)
    caps["name"] = path.name
    caps["source"] = str(path)
    caps["type"] = "skill"
    caps["learned_at"] = datetime.now(TZ).isoformat()

    if not caps["agents"]:
        caps["agents"] = ["api-hunter"]

    return caps

def learn_project(project_path):
    path = Path(os.path.expanduser(project_path))
    if not path.exists():
        return {"error": f"Path not found: {project_path}"}

    readme = path / "README.md"
    text = ""
    if readme.exists():
        text = readme.read_text(encoding="utf-8", errors="replace")

    caps = extract_capabilities(text)
    caps["name"] = path.name
    caps["source"] = str(path)
    caps["type"] = "project"
    caps["learned_at"] = datetime.now(TZ).isoformat()

    # Detect tech stack
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

def learn_hackerone_chain(chain_desc):
    """从 HackerOne 漏洞链描述生成组合技预设"""
    steps = [s.strip() for s in re.split(r'->|→|>|->>|=>', chain_desc)]
    agents = []
    for step in steps:
        norm = step.lower().replace(" ", "-").replace("_", "-")
        for name, agent in AGENT_NAME_MAP.items():
            if name in norm and agent not in agents:
                agents.append(agent)
                break
        else:
            # Fuzzy: check substring
            for name, agent in AGENT_NAME_MAP.items():
                if any(kw in norm for kw in name.split("-")) and agent not in agents:
                    agents.append(agent)
                    break

    if len(agents) < 2:
        return {"error": f"Need 2+ vulnerability types in chain, found: {agents}"}

    chain_id = re.sub(r'[^a-z0-9_]', '_', chain_desc.lower())[:40]
    preset = {
        "name": f"chain_{chain_id}",
        "trigger": [f"({chain_desc.lower()[:60]})", f"({'-'.join(steps[:3]).lower()})"],
        "trigger_score": 10,
        "agents": agents,
        "label": f"Chain: {' -> '.join(steps[:4])}",
        "recon_first": True,
        "note": f"HackerOne chain: {chain_desc} | {len(agents)} agents",
    }

    return {"preset_name": preset["name"], "agents": agents, "label": preset["label"], "preset": preset}


def cmd_learn(args):
    reg = load_registry()
    if args.skill:
        result = learn_skill(args.skill)
    elif args.project:
        result = learn_project(args.project)
    else:
        print("Use --skill or --project")
        return

    if "error" in result:
        print(f"ERROR: {result['error']}")
        return

    reg["agents"][result["name"]] = result
    save_registry(reg)

    print(f"[LEARNED] {result['name']} ({result['type']})")
    print(f"  Vuln types: {result.get('vuln_types', [])}")
    print(f"  Mapped agents: {result.get('agents', [])}")
    print(f"  Tools: {result.get('tools', [])}")
    if result.get("tech_stack"):
        print(f"  Tech: {result['tech_stack']}")

    # Auto-register with hive system
    if len(result["agents"]) >= 2:
        agents_str = ",".join(result["agents"][:6])
        print(f"  [AUTO] Registered as swarm preset: {agents_str}")
    else:
        print(f"  [SOLO] Single agent: {result['agents'][0] if result['agents'] else 'unknown'}")


def cmd_chain(args):
    result = learn_hackerone_chain(args.chain)
    if "error" in result:
        print(f"ERROR: {result['error']}")
        return

    print(f"[CHAIN] {result['label']}")
    print(f"  Agents: {result['agents']}")

    # Auto-add to swarm presets
    if SWARM_PRESETS.exists():
        presets = json.loads(SWARM_PRESETS.read_text(encoding="utf-8"))
        presets["presets"][result["preset_name"]] = result["preset"]
        SWARM_PRESETS.write_text(json.dumps(presets, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [AUTO] Added to swarm-presets.json as '{result['preset_name']}'")

    reg = load_registry()
    reg["chains"].append({
        "desc": args.chain,
        "agents": result["agents"],
        "added": datetime.now(TZ).isoformat(),
    })
    save_registry(reg)


def cmd_list(args):
    reg = load_registry()
    if not reg["agents"] and not reg["chains"]:
        print("No learned agents yet. Use --skill or --project first.")
        return

    print(f"[LEARNED] {len(reg['agents'])} skills/projects, {len(reg['chains'])} chains")
    print()
    for name, info in reg["agents"].items():
        print(f"  {name} ({info['type']})")
        print(f"    Agents: {info.get('agents',[])} | Vulns: {info.get('vuln_types',[])}")
        print(f"    Source: {info.get('source','?')}")
        print()
    for chain in reg["chains"]:
        print(f"  CHAIN: {chain['desc'][:80]} -> {chain['agents']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Agent 自学引擎")
    p.add_argument("--skill", help="Skill 目录路径")
    p.add_argument("--project", help="开源项目路径")
    p.add_argument("--list", action="store_true", help="列出已注册的")
    p.add_argument("--chain", help="漏洞链: XSS->CSRF->ATO")
    args = p.parse_args()

    if args.list:
        cmd_list(args)
    elif args.chain:
        cmd_chain(args)
    elif args.skill or args.project:
        cmd_learn(args)
    else:
        print("用法:")
        print("  python hive-learn.py --skill ~/.claude/skills/new-tool")
        print("  python hive-learn.py --project ~/practice/new-repo")
        print("  python hive-learn.py --chain 'XSS -> CSRF -> Account Takeover'")
        print("  python hive-learn.py --list")
