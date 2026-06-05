#!/usr/bin/env python3
"""
hive-dispatcher.py — 蜂群调度器
代替 dispatch-router 的单出口，复杂任务自动拆解为子任务并行派发。

模式:
  单个Agent: "帮我找一个Python库" → 匹配scout → 单派
  全面审计: "全面审计example.com" → 拆解为recon/sqli/xss/api/waf/smuggling → 并行5个Agent
  漏洞扫描: "扫一下这个站" → 按攻击面自动分派

输出: 3种
  1. stdout → hook statusMessage (简短)
  2. ~/.claude/data/hive-dispatch.json → 完整调度计划
  3. 自动调 hive-mind.py init → 创建共享大脑
"""
import json, os, re, sys, io, subprocess
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")

HOME = Path.home()
DATA = HOME / ".claude/data"
DATA.mkdir(parents=True, exist_ok=True)
PRESETS_FILE = HOME / ".claude/config/swarm-presets.json"
HIVE_CMD = str(HOME / ".claude/scripts/hive-mind.py")

# ── 读入 ──
prompt = ""
if not sys.stdin.isatty():
    try: prompt = sys.stdin.read()
    except: pass
if not prompt and len(sys.argv) > 1:
    prompt = " ".join(sys.argv[1:])
if not prompt:
    sys.exit(0)

prompt = prompt.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")
p = prompt.lower()

# ═══════════════════════════════════════════════════
# Agent 定义
# ═══════════════════════════════════════════════════
SEC_AGENTS = {
    "api-hunter":      ("api-hunter",      "API/GraphQL/JWT/IDOR/Mass Assignment"),
    "sql-injector":    ("sql-injector",    "SQL注入全谱 Union/Blind/Time/Stacked/OOB"),
    "xss-hunter":      ("xss-hunter",      "XSS全谱 Reflected/Stored/DOM/mXSS/CSP绕过"),
    "http-smuggler":   ("http-smuggler",   "HTTP走私 CL.TE/TE.CL/CL.0/H2.TE"),
    "confusion":       ("confusion-attacker", "语义混淆 Path Traversal/SSRF/Host Header"),
    "waf-bypasser":    ("waf-bypasser",    "WAF绕过 Cloudflare/AWS/ModSecurity/FortiWeb"),
    "race-condition":  ("race-condition",  "竞态条件 TOCTOU/并发支付/库存绕过"),
    "ad-pwn":          ("ad-pwn",          "Active Directory Kerberos/ADCS/DCSync"),
    "cloud-escape":    ("cloud-escape",    "容器逃逸 Kubernetes/Docker/AWS"),
    "mobile-reverser": ("mobile-reverser", "移动端逆向 Android/iOS APK"),
    "supply-chain":    ("supply-chain-hunter", "供应链攻击 npm/PyPI/CI-CD"),
    "web3-auditor":    ("web3-auditor",    "智能合约审计 Solidy/DeFi"),
    "llm-redteamer":   ("llm-redteamer",   "LLM攻击 Prompt Injection/RAG"),
    "binary-exploiter":("binary-exploiter","二进制利用 ROP/Heap/Kernel"),
    "bb-methodologist":("bug-bounty-methodologist", "赏金方法论"),
    "report-humanizer":("report-humanizer","报告去AI味"),
}

PI_AGENTS = {
    "scout":    ("scout",    "搜索信息收集"),
    "dev":      ("dev",      "编码实现"),
    "recon":    ("recon",    "资产侦察"),
    "reporter": ("reporter", "报告文档"),
    "browser":  ("browser",  "浏览器操作"),
    "ops":      ("ops",      "运维部署"),
}

# ═══════════════════════════════════════════════════
# 蜂群组合 — 从预设库动态加载（可随时编辑 swarm-presets.json）
# ═══════════════════════════════════════════════════
def load_swarm_presets():
    if PRESETS_FILE.exists():
        try:
            presets = json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
            result = {}
            for name, cfg in presets.get("presets", {}).items():
                # 把 trigger 数组编译成 (regex, score) 列表
                trigger_binds = [(t, cfg.get("trigger_score", 9)) for t in cfg["trigger"]]
                result[name] = {
                    "triggers": trigger_binds,
                    "agents": cfg["agents"],
                    "recon_first": cfg.get("recon_first", False),
                    "label": cfg.get("label", f"蜂群: {name}"),
                    "note": cfg.get("note", ""),
                }
            return result
        except Exception:
            pass
    # Fallback: 最小预设集
    return {
        "quick_web_scan": {
            "triggers": [(r"(快扫|扫一下|扫一扫|查.*漏洞|看.*有没有.*漏洞|light.*scan)|scan.*(site|web|url|网站)", 8)],
            "agents": ["api-hunter", "sql-injector", "xss-hunter", "waf-bypasser"],
            "label": "⚡ 蜂群模式: 快速Web扫描",
        },
        "basic_web": {
            "triggers": [(r"(审计|扫描|测试|找.*漏洞|检查|security|pentest).*(这个|网站|目标|域名|url|app|系统|web|http|代码|源码)", 7)],
            "agents": ["api-hunter", "sql-injector", "xss-hunter"],
            "label": "🐝 蜂群模式: 基础Web审计",
        },
    }

SWARM_PRESETS = load_swarm_presets()

# ═══════════════════════════════════════════════════
# 单Agent匹配规则 (fallback)
# ═══════════════════════════════════════════════════
SEC_SOLO_RULES = [
    (r"sql.*注入|sqli\b|sqlmap|盲注|联合查询|堆叠查询", "sql-injector", 11),
    (r"(?<![a-zA-Z])xss(?![a-zA-Z])|cross.*site.*script|反射.*xss|存储.*xss|csp.*绕过", "xss-hunter", 11),
    (r"http.*(smuggl|走私|desync)|cl\.0|cl\.te|te\.cl|h2\.te", "http-smuggler", 11),
    (r"waf.*(绕|bypass|规避)|cloudflare.*绕|modsecurity.*绕", "waf-bypasser", 11),
    (r"竞态|race.*condition|toctou|单包攻击|并发.*漏洞", "race-condition", 11),
    (r"graphql|jwt.*(攻击|inject|none|alg|绕过|弱密钥)|mass.*assign|idor|bola", "api-hunter", 11),
    (r"智能合约.*审计|solidity.*安全|defi.*攻击|reentranc|闪电贷", "web3-auditor", 11),
    (r"进制.*利用|rop.*链|栈.*溢出|堆.*溢出|pwntools|buffer.*overflow", "binary-exploiter", 11),
    (r"active.*director|kerberos|域控|域渗透|dcsync|bloodhound", "ad-pwn", 11),
    (r"容器.*逃逸|docker.*escape|kubernetes.*攻击|云原生.*安全", "cloud-escape", 11),
    (r"android.*逆向|ios.*越狱|frida|apk.*逆向|移动.*安全", "mobile-reverser", 11),
    (r"供应链.*攻击|npm.*恶意|pypi.*恶意|typosquat|依赖.*投毒", "supply-chain", 11),
    (r"llm.*攻击|prompt.*inject|ai.*agent.*安全|rag.*攻击", "llm-redteamer", 11),
    (r"去.*ai.*味|humaniz.*report|润色.*报告", "report-humanizer", 11),
    (r"bug.*bounty.*(方法|技巧|入门|方法)|赏金.*(猎人|入门|怎么)", "bb-methodologist", 10),
]

# ═══════════════════════════════════════════════════
# 拆解逻辑
# ═══════════════════════════════════════════════════
def detect_swarm_mode(text):
    all_matches = []
    for name, cfg in SWARM_PRESETS.items():
        for pat, score in cfg.get("triggers", []):
            if re.search(pat, text):
                all_matches.append((score, name, cfg))
                break
    all_matches.sort(key=lambda x: -x[0])
    if all_matches:
        score, name, cfg = all_matches[0]
        return name, cfg, score
    return None, None, 0

def detect_solo_agent(text):
    """单Agent匹配"""
    matches = []
    for pat, agent, score in SEC_SOLO_RULES:
        if re.search(pat, text):
            matches.append((score, agent))
    matches.sort(key=lambda x: -x[0])
    return matches[0] if matches else (0, None)

# ═══════════════════════════════════════════════════
# 安全关键词检测
# ═══════════════════════════════════════════════════
SEC_PAT = r"(安全|漏洞|审计|bounty|赏金|渗透|pentest|hack|exploit|vuln|攻击|走私|desync|注入|injection|ssrf|csrf|xss|ssti|idor|bola|sqli|sqlmap|绕|bypass|逃逸|escape|提权|privesc|waf|竞态|并发|注入|malware|木马|webshell|后门|扫描|扫一下|扫一扫|查漏洞|找漏洞|挖洞|代码审计|测试.*漏洞|bug.*bounty|帮我.*(审计|扫描|找|查|测)|api.*(审计|安全|测试)|django|express|node\.js|rust|golang|java.*(审计|安全)|帮我.*看|帮我.*测|帮我.*分析)"
is_security = bool(re.search(SEC_PAT, p))

# ═══════════════════════════════════════════════════
# 主调度
# ═══════════════════════════════════════════════════
if not is_security:
    # 非安全 → 退回PI路由
    (DATA / "hive-dispatch.json").write_text(
        json.dumps({"mode": "non_security", "prompt": prompt[:200]}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    sys.exit(0)

# 安全场景 → hive-brain 智能分析优先
BRAIN = str(HOME / ".claude/scripts/hive-brain.py")
BRAIN_INPUT = str(DATA / "brain-input.txt")
brain_agents = []
try:
    # 写文件避免Windows subprocess管道编码问题
    Path(BRAIN_INPUT).write_text(prompt, encoding="utf-8")
    r = subprocess.run([sys.executable, BRAIN, "--from-file", BRAIN_INPUT],
                       capture_output=True, timeout=8, encoding="utf-8")
    out = r.stdout + r.stderr
    for line in out.split("\n"):
        if line.startswith("__BRAIN_FILE__"):
            brain_result_file = line[16:]
            if Path(brain_result_file).exists():
                brain_data = json.loads(Path(brain_result_file).read_text(encoding="utf-8"))
                brain_agents = brain_data.get("agents", [])
            break
except Exception:
    pass

solo_score, solo_agent = detect_solo_agent(p)

# ── 调度决策 ──
if brain_agents and len(brain_agents) >= 2:
    # 🧠 大脑模式 — hive-brain 自己分析出了Agent组合
    swarm_name, swarm_cfg, swarm_score = "brain", {
        "agents": brain_agents,
        "label": f"🧠 蜂巢大脑分析: {len(brain_agents)} Agent",
        "recon_first": True,
    }, 12
else:
    # 预设fallback
    swarm_name, swarm_cfg, swarm_score = detect_swarm_mode(p)

# 决策: 蜂群优先（团队优势: +3 bonus）
SWARM_BONUS = 3
if swarm_cfg and (swarm_score + SWARM_BONUS) >= solo_score:
    # ── 蜂群模式 ──
    plan = {
        "mode": "swarm",
        "label": swarm_cfg["label"],
        "swarm": swarm_name,
        "agents": swarm_cfg["agents"],
        "agent_count": len(swarm_cfg["agents"]),
        "recon_first": swarm_cfg.get("recon_first", False),
        "prompt": prompt[:300],
    }
    (DATA / "hive-dispatch.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    # 初始化蜂巢 + 全部入队
    target = re.sub(r'(全面|完整|全站|彻底|快速)?\s*(审计|扫描|测试|评估|渗透|检查|找漏洞)\s*(这个|那个|一下|)?', '', prompt).strip()
    if not target:
        target = prompt[:80]
    subprocess.run([sys.executable, HIVE_CMD, "init", target], capture_output=True)
    for a in swarm_cfg["agents"]:
        subprocess.run([sys.executable, HIVE_CMD, "queue", "--add", a], capture_output=True)

    agent_list = ", ".join(swarm_cfg["agents"])
    print(f"{plan['label']} | {len(swarm_cfg['agents'])} Agent: {agent_list} | 🧠 hive-mind 已启动")

    # 写 current-match 给 inject-kb 用
    (DATA / "current-match.json").write_text(json.dumps({
        "mode": "swarm",
        "agents": swarm_cfg["agents"],
        "is_security": True,
        "prompt_snippet": prompt[:200],
        "swarm": swarm_name,
        "hive_active": True,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

elif solo_agent:
    # ── 单Agent模式 ──
    plan = {
        "mode": "solo",
        "agent": solo_agent,
        "skill": SEC_AGENTS.get(solo_agent, (solo_agent, ""))[1],
        "score": solo_score,
        "prompt": prompt[:300],
    }
    (DATA / "hive-dispatch.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    emoji = {"sql-injector": "💉", "xss-hunter": "🔥", "http-smuggler": "🌊", "waf-bypasser": "🛡️",
             "api-hunter": "🔌", "confusion-attacker": "🌀", "race-condition": "⚡", "web3-auditor": "⛓️",
             "binary-exploiter": "💀", "ad-pwn": "🏰", "cloud-escape": "☁️", "mobile-reverser": "📱",
             "supply-chain-hunter": "📦", "llm-redteamer": "🤖", "bug-bounty-methodologist": "💰",
             "report-humanizer": "📝"}
    e = emoji.get(solo_agent, "🛡️")
    print(f"{e} 单兵: {solo_agent} | ⭐{solo_score}/12 | {SEC_AGENTS.get(solo_agent, (solo_agent, ''))[1][:50]}")

    # 单兵也初始化蜂巢（方便后面扩展）
    target = prompt[:80]
    subprocess.run([sys.executable, HIVE_CMD, "init", target], capture_output=True)

    (DATA / "current-match.json").write_text(json.dumps({
        "mode": "solo",
        "agent": solo_agent,
        "is_security": True,
        "prompt_snippet": prompt[:200],
        "hive_active": True,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

else:
    # 安全关键词但无精确匹配 → 让主模型决定
    (DATA / "hive-dispatch.json").write_text(
        json.dumps({"mode": "security_ambiguous", "prompt": prompt[:200]}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    sys.exit(0)

sys.exit(0)
