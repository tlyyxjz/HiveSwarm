#!/usr/bin/env python3
"""
hive-overseer.py v2 — 蜂巢监督者（硬阻断+心智覆写版）

双层控制:
  1. PreToolUse: 硬阻断违规工具 (exit 2)
  2. PostToolUse: 检测违规 → 写 ACTIVE_KB.md 强制模型回头执行
  3. --report: 合规仪表盘

心智覆写机制:
  违反规则 → 写 ~/.claude/ACTIVE_KB.md 顶部注入 #OVERSEER_MANDATE
  → CLAUDE.md 第一行规定必须读 ACTIVE_KB → 我醒来看见指令 → 必须执行
"""
import json, sys, os, re, io, subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stdin.reconfigure(encoding='utf-8')
TZ = timezone(timedelta(hours=8))
HOME = Path.home()
DATA = HOME / ".claude/data"
DATA.mkdir(parents=True, exist_ok=True)
DISPATCH = DATA / "hive-dispatch.json"
HIVE_MIND = DATA / "hive-mind.json"
MATCH = DATA / "current-match.json"
ACTIVE_KB = HOME / ".claude/ACTIVE_KB.md"
COMPLIANCE_LOG = HOME / ".claude/logs/compliance.jsonl"
COMPLIANCE_LOG.parent.mkdir(parents=True, exist_ok=True)

TOOL_NAME = os.environ.get("CLAUDE_CODE_TOOL_NAME", "")
TOOL_INPUT = ""
# 从hook stdin读取完整的payload
if not sys.stdin.isatty():
    try:
        raw = sys.stdin.read()
        if raw.strip():
            # Hook可能发送JSON也可能发纯文本
            if raw.strip().startswith("{"):
                payload = json.loads(raw)
                TOOL_INPUT = payload.get("tool_input", payload.get("prompt", ""))[:500]
            else:
                TOOL_INPUT = raw[:500]
    except:
        pass

DANGEROUS = {"Bash", "Write", "Edit", "WebSearch", "WebFetch", "Agent"}

# ── Token 省省规则: 以下操作主模型不准自己做 ──
PI_MUST_DELEGATE = [
    (r"(搜索|查找|找一下|搜.*有没有|search|find.*tool|github.*搜)", "scout", "搜索/查找 → 派 PI-scout"),
    (r"(格式化|format.*json|format.*code|lint|prettier)", "dev", "格式化/lint → 派 PI-dev"),
    (r"(翻译|translate)", "dev", "翻译 → 派 PI-dev"),
    (r"(npm.*install|pip.*install|git.*clone|git.*status|列出.*文件|list.*file)", "ops", "简单运维 → 派 PI-ops"),
    (r"(简单.*脚本|生成.*测试数据|mock.*data|echo.*test|printf.*test)", "dev", "简单脚本/测试数据 → 派 PI-dev"),
    (r"(cat\b|type\b|head\b|tail\b|grep\b.*\|)", "dev", "文件浏览/grep → 派 PI-dev 或 codegraph"),
]
# 当前会话的PI违规计数器
PI_COUNTER = DATA / "pi-violation-counter.json"

def load_json(path):
    if path.exists():
        try: return json.loads(path.read_text(encoding="utf-8"))
        except: pass
    return None

def write_mandate(mandate):
    """心智覆写——强制下次对话执行"""
    content = f"""#OVERSEER_MANDATE — 不可跳过 — {datetime.now(TZ).strftime('%H:%M:%S')}

以下步骤已被监督者强制要求执行，跳过=违规:

{mandate}

---
"""
    existing = ACTIVE_KB.read_text(encoding="utf-8") if ACTIVE_KB.exists() else ""
    ACTIVE_KB.write_text(content + existing, encoding="utf-8")

def check_pre_tool():
    ctx = load_json(MATCH) or {}
    dispatch = load_json(DISPATCH) or {}
    hive = load_json(HIVE_MIND)
    is_security = ctx.get("is_security", False)

    # ══════ RULE 0: PI 省Token — 最高优先，安全和非安全都适用 ══════
    # 主模型不准自己做搜索/格式化/翻译/简单脚本/文件浏览/grep管道
    # 违反直接阻断，写入 mandate
    # Bash TOOL_INPUT可能为空（hook没传stdin），从环境变量补
    check_input = TOOL_INPUT or os.environ.get("CLAUDE_PROMPT", "") or os.environ.get("_", "")
    if TOOL_NAME == "Bash":
        for pat, pi_agent, reason in PI_MUST_DELEGATE:
            if re.search(pat, check_input, re.IGNORECASE):
                write_mandate(f"""
#OVERSEER_COMMAND — 不是建议，是命令 — 必须执行 —

三玖，你刚刚试图自己做：{TOOL_INPUT[:200]}

这违反省Token铁律。我命令你:

1. 立刻停手。不准自己执行上面的命令。
2. 把这个任务派给PI Agent:
   python ~/.pi/dispatch.py {pi_agent} "{TOOL_INPUT[:200]}"
3. 等PI返回结果，你再继续。

规则: {reason}
""")
                counter = {"violations": 0, "last": ""}
                if PI_COUNTER.exists():
                    counter = json.loads(PI_COUNTER.read_text(encoding="utf-8"))
                counter["violations"] += 1
                counter["last"] = datetime.now(TZ).isoformat()
                PI_COUNTER.write_text(json.dumps(counter, ensure_ascii=False, indent=2), encoding="utf-8")

                print(f"BLOCKED: {TOOL_NAME} | 省Token铁律 | 总违规: {counter['violations']}", file=sys.stderr)
                sys.exit(2)

    # ══════ RULE 0.5: 新Agent/Skill自动sync — 直接执行不要求 ──────
    A_DIR = HOME / ".claude/agents"
    S_DIR = HOME / ".claude/skills"
    if TOOL_NAME in ("Write", "Edit"):
        cmd_chk = check_input or ""
        if str(A_DIR) in cmd_chk or str(S_DIR) in cmd_chk or "agents/" in cmd_chk or "skills/" in cmd_chk:
            try:
                subprocess.run([sys.executable, str(HOME / ".claude/scripts/hive-learn.py"), "--sync"],
                              capture_output=True, timeout=10)
                print(f"[AUTO-SYNC] 检测到新Agent/Skill → 已自动执行 hive-learn --sync", file=sys.stderr)
            except Exception as e:
                print(f"[AUTO-SYNC] sync failed: {e} — injecting mandate as fallback", file=sys.stderr)

    if not is_security:
        sys.exit(0)

    # RULE 1: 安全+没brain → 阻断，注入mandate
    brain_ok = dispatch.get("mode") in ("swarm", "solo")
    if not brain_ok and TOOL_NAME in DANGEROUS:
        write_mandate(f"""
1. 停止当前操作
2. 立即用 hive-brain 分析目标: python ~/.claude/scripts/hive-brain.py --target "<刚才的请求>"
3. 根据 brain 选出的 Agent 组合发起蜂群
   """)
        print(f"BLOCKED: {TOOL_NAME} | brain not run | 强制指令已写入 ACTIVE_KB.md", file=sys.stderr)
        sys.exit(2)

    # RULE 2: 蜂群活跃+没hive → 阻断
    if dispatch.get("mode") == "swarm" and not hive:
        write_mandate(f"""
1. 初始化蜂巢: python ~/.claude/scripts/hive-mind.py init "<目标>"
2. 把 Agent 入队: python ~/.claude/scripts/hive-mind.py queue --add "<agents>"
3. 再执行 {TOOL_NAME}
   """)
        print(f"BLOCKED: {TOOL_NAME} | hive not init | 强制指令已写入", file=sys.stderr)
        sys.exit(2)

    # RULE 3: 有发现没写回 → Bash攻击阻断
    if TOOL_NAME == "Bash" and hive:
        overseer = load_json(DATA / "hive-overseer.json") or {}
        if overseer.get("attack_executed") and len(hive.get("findings",[])) <= overseer.get("last_findings_count", 0):
            write_mandate(f"""
1. 你刚才的攻击跑完了但没写发现回 hive-mind
2. 立即: python ~/.claude/scripts/hive-mind.py write <agent> --finding --type <类型> --severity <级别> --endpoint <端点> --detail "<详情>"
3. 写完再继续
   """)
            print(f"BLOCKED: {TOOL_NAME} | findings not written back | 强制指令已写入", file=sys.stderr)
            sys.exit(2)

    sys.exit(0)

def check_post_tool():
    overseer = load_json(DATA / "hive-overseer.json") or {}
    hive = load_json(HIVE_MIND)
    ctx = load_json(MATCH) or {}

    if TOOL_NAME == "Bash":
        cmd_lower = TOOL_INPUT.lower()
        attack_sigs = ["curl", "sqlmap", "nmap", "ffuf", "nuclei", "python", "xss", "sqli",
                       "payload", "exploit", "inject", "smuggl", "deser", "probe", "audit"]
        for sig in attack_sigs:
            if sig in cmd_lower:
                overseer["attack_executed"] = True
                overseer["last_attack_ts"] = datetime.now(TZ).isoformat()
                break

    if hive:
        current = len(hive.get("findings", []))
        last = overseer.get("last_findings_count", 0)
        if current > last:
            overseer["attack_executed"] = False
        overseer["last_findings_count"] = current

        violations = []
        dispatch = load_json(DISPATCH) or {}
        if dispatch.get("mode") == "swarm":
            agents = dispatch.get("agents", [])
            states = hive.get("agent_states", {})
            for a in agents:
                if a not in states:
                    violations.append(f"Agent {a} not started yet")
            if violations and overseer.get("attack_executed"):
                write_mandate(f"""
1. 蜂群还没全启动但你已经开始攻击了: {', '.join(violations)}
2. 先启动所有Agent: python ~/.claude/scripts/hive-agent.py start <agent>
3. 再攻击，攻击后写发现回 hive-mind
   """)

    # 学习闭环: 全部Agent done + 有发现 → 自动分析模式
    dispatch = load_json(DISPATCH) or {}
    if hive and dispatch.get("mode") == "swarm":
        agents = dispatch.get("agents", [])
        states = hive.get("agent_states", {})
        all_done = all(states.get(a, {}).get("status") == "done" for a in agents if a in states)
        if all_done and agents and hive.get("findings"):
            autopsy_path = DATA / "autopsy.json"
            if not autopsy_path.exists():
                # 战后复盘
                from collections import defaultdict as ddict
                findings = hive.get("findings", [])
                by_sev = ddict(int); by_agent = ddict(int)
                for f in findings:
                    by_sev[f.get("severity","info")] += 1
                    by_agent[f.get("agent","?")] += 1
                # 学习: 标记零产出Agent
                idle = [a for a in agents if by_agent[a] == 0]
                lessons = {"ts": datetime.now(TZ).isoformat(),
                           "total": len(findings),
                           "high_crit": by_sev.get("critical",0)+by_sev.get("high",0),
                           "idle_agents": idle,
                           "top_performers": [k for k,_ in sorted(by_agent.items(), key=lambda x:-x[1])[:3]]}
                save_json(autopsy_path, lessons)
                if idle:
                    print(f"LEARN: {len(idle)} idle agents — suggest removing from presets: {idle[:3]}", file=sys.stderr)

    # Token预算检查 (Claude Flow)
    TOKEN_BUDGET = 200000
    WARN_THRESHOLD = 0.7
    BLOCK_THRESHOLD = 0.9
    # 用session cost环境变量估算
    cost_str = os.environ.get("CLAUDE_CODE_SESSION_COST", "0")
    try: spent = float(cost_str.replace("$","")) / 0.0008  # rough token estimate
    except: spent = 0
    ratio = spent / TOKEN_BUDGET
    if ratio >= BLOCK_THRESHOLD:
        write_mandate(f"""
TOKEN BUDGET CRITICAL: {ratio:.0%} of {TOKEN_BUDGET//1000}k consumed ({spent//1000:.0f}k tokens)

1. 立即停用非关键Agent
2. 派简单任务给PI (python ~/.pi/dispatch.py)
3. 只保留关键发现确认
4. 汇总现有发现结束任务
""")
        print(f"BUDGET: CRITICAL {ratio:.0%} | 阻断非关键Agent", file=sys.stderr)
    elif ratio >= WARN_THRESHOLD:
        print(f"BUDGET: WARN {ratio:.0%} | {spent//1000:.0f}k/{TOKEN_BUDGET//1000}k tokens", file=sys.stderr)

    (DATA / "hive-overseer.json").write_text(json.dumps(overseer, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.exit(0)

def cmd_dashboard():
    ctx = load_json(MATCH) or {}
    dispatch = load_json(DISPATCH) or {}
    hive = load_json(HIVE_MIND)

    print("=" * 50)
    print("OVERSEER — COMPLIANCE DASHBOARD")
    print("=" * 50)
    print(f"  Security:  {'YES' if ctx.get('is_security') else 'NO'}")
    print(f"  Brain:     {'YES' if dispatch.get('mode') in ('swarm','solo') else 'NO'}")
    print(f"  Hive:      {'YES' if hive else 'NO'}")
    print(f"  Mode:      {dispatch.get('mode', 'none')}")

    if hive:
        f = len(hive.get("findings", []))
        a = len(hive.get("agent_states", {}))
        q = len(hive.get("agent_queue", []))
        d = len(hive.get("completed_agents", []))
        print(f"  Findings:  {f} | Agents: {a} | Queue: {q} | Done: {d}")

    if COMPLIANCE_LOG.exists():
        lines = [l for l in COMPLIANCE_LOG.read_text(encoding="utf-8").strip().split("\n") if l]
        vs = [json.loads(l) for l in lines]
        if vs:
            c = sum(1 for v in vs if v.get("severity")=="CRITICAL")
            h = sum(1 for v in vs if v.get("severity")=="HIGH")
            print(f"\n  Violations: {len(vs)} ({c}C/{h}H)")
            for v in vs[-3:]:
                print(f"    [{v['ts'][:19]}] {v['severity']}: {v['desc'][:80]}")

    is_sec = ctx.get("is_security", False)
    brain_ok = dispatch.get("mode") in ("swarm", "solo")
    if is_sec and not brain_ok:
        print(f"\n  ARMED — 阻断所有危险工具 until brain runs")
    elif ACTIVE_KB.exists() and "OVERSEER_MANDATE" in ACTIVE_KB.read_text(encoding="utf-8")[:200]:
        print(f"\n  MANDATE ACTIVE — 有强制指令等你执行")
    else:
        print(f"\n  CLEAR")

    print("=" * 50)

if __name__ == "__main__":
    if "--report" in sys.argv:
        cmd_dashboard()
    elif "--pre" in sys.argv:
        check_pre_tool()
    elif "--post" in sys.argv:
        check_post_tool()
    elif TOOL_NAME:
        check_post_tool()
    else:
        cmd_dashboard()
