#!/usr/bin/env python3
"""
hive-brain.py — 蜂巢大脑决策器
读安全报告/目标描述 → 自动分析攻击面 → 选出Agent组合 → 发起蜂群

用法:
  python hive-brain.py --report audit-report.md    → 读报告自动选Agent
  python hive-brain.py --target "Node.js + MySQL + JWT 的电商API" → 根据技术栈自动选
  python hive-brain.py --url https://xxx.com --auto → 全自动分析
"""
import json, re, sys, os, argparse, subprocess, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

HOME = Path.home()
HIVE = str(HOME / ".claude/scripts/hive-mind.py")
DATA = HOME / ".claude/data"
DATA.mkdir(parents=True, exist_ok=True)

AGENT_CAPABILITIES = {
    "api-hunter":       {"keys": ["api","rest","graphql","jwt","idor","bola","mass.*assign","swagger","openapi","endpoint","接口","越权","未授权","权限"], "weight": 1},
    "sql-injector":     {"keys": ["sql","injection","sqli","sqlmap","query","select","insert","update","delete","database","注入","数据库","查询","mysql","postgres","mssql","oracle","sqlite"], "weight": 1},
    "xss-hunter":       {"keys": ["xss","cross.*site","script","alert","onerror","dom","html.*inject","反射","存储","html","javascript","dom","csp"], "weight": 1},
    "http-smuggler":    {"keys": ["smuggl","desync","http.*2","http/1","cl\\.0","cl\\.te","te\\.cl","走私","去同步","proxy","cdn","waf.*front","frontend"], "weight": 1},
    "waf-bypasser":     {"keys": ["waf","cloudflare","modsecurity","fortiweb","imperva","防火墙","bypass","绕过","tamper","filter","过滤","拦截","blocked","403"], "weight": 1},
    "confusion":        {"keys": ["path.*traversal","ssrf","host.*header","url.*pars","ambigu","confus","路径.*穿越","目录.*遍历","文件.*读取","歧义","混淆","forward","redirect"], "weight": 1},
    "race-condition":   {"keys": ["race","toctou","竞态","并发","parallel","turbo.*intruder","time.*window","优惠券","库存","超卖","重复.*下单","限流","rate.*limit"], "weight": 1},
    "supply-chain":     {"keys": ["supply.*chain","供应链","npm","pypi","dependency","package\\.json","依赖","包管理","typosquat","malicious.*package","恶意.*包","ci.*cd","github.*action","dockerfile","container.*image"], "weight": 1},
    "binary-exploiter": {"keys": ["binary","exploit","反序列化","deserializ","unserializ","node.serialize","pickle","yaml.*load","buffer.*overflow","rop","栈.*溢出","堆.*溢出","pwntools","cve.*rce","rce","代码执行","命令执行"], "weight": 1},
    "cloud-escape":     {"keys": ["cloud","aws","azure","gcp","kubernetes","k8s","docker","容器","逃逸","escape","ec2","s3","iam","lambda","terraform","cloudformation","弹性.*计算","云.*服务"], "weight": 1},
    "mobile-reverser":  {"keys": ["android","ios","apk","ipa","frida","jadx","移动","mobile","app.*逆向","ssl.*pinning","cert.*pin","越狱","hook","smali","dex"], "weight": 1},
    "web3-auditor":     {"keys": ["web3","solidity","smart.*contract","defi","reentranc","闪电贷","flash.*loan","智能合约","区块链","ethereum","evm","metamask","wallet","nft","token.*contract"], "weight": 1},
    "llm-redteamer":    {"keys": ["llm","ai.*agent","rag","prompt.*inject","langchain","chatgpt","gpt","openai","模型.*攻击","大模型","生成式.*ai","gen.*ai","copilot","agent.*安全"], "weight": 1},
    "ad-pwn":           {"keys": ["active.*directory","kerberos","domain.*controller","域控","域.*渗透","dcsync","bloodhound","adcs","ldap","ntlm","smb","windows.*domain","ad.*环境"], "weight": 1},
    "bb-methodologist": {"keys": ["bug.*bounty","赏金","hackerone","bugcrowd","src","漏洞盒子","补天","recon","侦察","信息收集","subdomain","子域","passive.*recon","hunting.*methodology"], "weight": 1},
    "report-humanizer": {"keys": ["报告","report","writeup","文档","总结","输出","去.*ai","humaniz","润色"], "weight": 0.5},
}

TECH_STACK_HINTS = {
    "node":    ["api-hunter","sql-injector","binary-exploiter","supply-chain"],
    "express": ["api-hunter","sql-injector","xss-hunter"],
    "react":   ["xss-hunter","api-hunter"],
    "vue":     ["xss-hunter","api-hunter"],
    "django":  ["api-hunter","sql-injector","xss-hunter"],
    "flask":   ["api-hunter","sql-injector","xss-hunter"],
    "spring":  ["api-hunter","sql-injector","confusion"],
    "laravel": ["api-hunter","sql-injector","xss-hunter"],
    "mysql":   ["sql-injector"],
    "postgres":["sql-injector"],
    "mssql":   ["sql-injector","ad-pwn"],
    "mongodb": ["api-hunter","sql-injector"],
    "redis":   ["api-hunter"],
    "graphql": ["api-hunter"],
    "jwt":     ["api-hunter"],
    "docker":  ["cloud-escape","supply-chain"],
    "k8s":     ["cloud-escape"],
    "aws":     ["cloud-escape","api-hunter"],
    "react-native": ["mobile-reverser"],
    "flutter": ["mobile-reverser"],
    "solidity":["web3-auditor"],
    "nginx":   ["confusion"],
    "apache":  ["confusion"],
    "iis":     ["confusion"],
}

def analyze_text(text):
    scores = {}
    evidence = {}

    for agent, cfg in AGENT_CAPABILITIES.items():
        s = 0
        matches = []
        for key in cfg["keys"]:
            found = re.findall(key, text, re.IGNORECASE)
            if found:
                s += len(found) * cfg["weight"]
                matches.append(key)
        if s > 0:
            scores[agent] = s
            evidence[agent] = matches[:6]

    # Tech stack bonus
    for tech, agents in TECH_STACK_HINTS.items():
        if re.search(rf"\b{tech}\b", text, re.IGNORECASE):
            for a in agents:
                scores[a] = scores.get(a, 0) + 2

    # WAF bonus — 有URL时默认加waf-bypasser
    if re.search(r"https?://", text):
        scores["waf-bypasser"] = scores.get("waf-bypasser", 0) + 1
        scores["bb-methodologist"] = scores.get("bb-methodologist", 0) + 1
        if not any(k in text.lower() for k in ["waf","cloudflare","modsecurity","防火墙"]):
            scores["waf-bypasser"] = max(scores["waf-bypasser"], 1)

    ranked = sorted(scores.items(), key=lambda x: -x[1])
    return ranked, evidence


def select_agents(ranked, max_agents=8):
    threshold = max(1, ranked[0][1] * 0.25) if ranked else 0
    agents = [r[0] for r in ranked if r[1] >= threshold]
    return agents[:max_agents]


def determine_mode(agents):
    n = len(agents)
    if n >= 12: return "apocalypse"
    if n >= 8:  return "spider"
    if n >= 5:  return "full_web"
    if n >= 3:  return "quick_scan"
    return "solo"


def cmd_analyze(args):
    text = ""
    if args.report:
        p = Path(args.report)
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="replace")
        else:
            print(f"❌ 文件不存在: {args.report}")
            sys.exit(1)
    elif args.from_file:
        p = Path(args.from_file)
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="replace")
        else:
            print(f"❌ 文件不存在: {args.from_file}")
            sys.exit(1)
    elif args.target:
        text = args.target
    elif args.url:
        text = f"Target URL: {args.url}\nFull security audit required."
    else:
        text = sys.stdin.read()

    ranked, evidence = analyze_text(text)
    if not ranked:
        print("❌ 无法从输入中识别攻击面，请提供更多信息")
        sys.exit(1)

    agents = select_agents(ranked)
    mode = determine_mode(agents)

    print(f"🧠 蜂巢分析结果:")
    print(f"   输入: {'报告文件' if args.report else '描述文本'} ({len(text)} 字符)")
    print(f"   模式: {mode}")
    print(f"   推荐 Agent ({len(agents)}): {', '.join(agents)}")
    # JSON结果 — 受Windows gbk限制改用文件输出
    result_file = str(Path.home() / ".claude/data/brain-result.json")
    Path(result_file).write_text(json.dumps({"agents": agents, "mode": mode}, ensure_ascii=False), encoding="utf-8")
    print(f"__BRAIN_FILE__{result_file}")
    print()

    print("📊 评分明细:")
    for agent, score in ranked[:12]:
        ev = evidence.get(agent, [])
        bar = "█" * min(int(score), 20)
        print(f"   {agent:20s} {bar} [{score}]")
        if ev:
            print(f"   {'':20s} 证据: {', '.join(ev[:4])}")
    print()

    if args.execute:
        target = args.url or "从报告/描述推断的目标"
        agents_str = ",".join(agents)
        print(f"⚡ 发起蜂群: {len(agents)} Agent → {target}")
        subprocess.run([sys.executable, HIVE, "init", target], capture_output=True)
        subprocess.run([sys.executable, HIVE, "queue", "--add", agents_str], capture_output=True)
        subprocess.run([sys.executable, HIVE, "status"], capture_output=False)
    else:
        print(f"💡 要发起蜂群? 加 --execute --url <目标>")

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="蜂巢大脑 — 自动分析攻击面选Agent")
    p.add_argument("--report", help="审计报告/漏洞报告文件路径")
    p.add_argument("--from-file", help="从文件读取目标描述（Windows管道兼容）")
    p.add_argument("--target", help="目标描述文本")
    p.add_argument("--url", help="目标URL")
    p.add_argument("--execute", action="store_true", help="自动发起蜂群")
    args = p.parse_args()

    if not any([args.report, args.from_file, args.target, args.url]):
        print("用法: python hive-brain.py --report audit.md --url https://x.com --execute")
        sys.exit(0)

    cmd_analyze(args)
