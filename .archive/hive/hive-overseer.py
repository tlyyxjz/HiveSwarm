#!/usr/bin/env python3
"""overseer v3 — PostToolUse计数+写flag → PreToolUse读flag阻断"""
import json, sys, os, re, io, subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
TZ = timezone(timedelta(hours=8))
HOME = Path.home()
DATA = HOME / ".claude/data"
DATA.mkdir(parents=True, exist_ok=True)
DISPATCH = DATA / "hive-dispatch.json"
HIVE_MIND = DATA / "hive-mind.json"
MATCH = DATA / "current-match.json"
ACTIVE_KB = HOME / ".claude/ACTIVE_KB.md"
STATE = DATA / "overseer-state.json"

TOOL = os.environ.get("CLAUDE_CODE_TOOL_NAME", "")

def ld(p):
    if p.exists():
        try: return json.loads(p.read_text(encoding="utf-8"))
        except: pass
    return None

def sv(p, d):
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

def mandate(msg):
    h = datetime.now(TZ).strftime('%H:%M:%S')
    ACTIVE_KB.write_text(f"#OVERSEER — {h}\n{msg}\n---\n" + (ACTIVE_KB.read_text(encoding="utf-8") if ACTIVE_KB.exists() else ""), encoding="utf-8")

# ── PreToolUse: 读flag阻断 ──
def pre():
    s = ld(STATE) or {"bash_count":0,"pi_warn":0,"hive_miss":0,"last_ts":""}
    ctx = ld(MATCH) or {}
    dispatch = ld(DISPATCH) or {}
    is_sec = ctx.get("is_security", False)

    # PI WARNING: 3+ Bashes in under 60s → force delegate
    if s.get("pi_warn", 0) >= 2 and TOOL == "Bash":
        mandate("#OVERSEER_COMMAND: 你连续多次用Bash自己做。派PI: python ~/.pi/dispatch.py <agent> '<task>'")
        print("BLOCKED: 连用Bash太多 → 强派PI", file=sys.stderr)
        s["pi_warn"] = 0; sv(STATE, s)
        sys.exit(2)

    # HIVE FLOW: 安全场景+brain没跑+要动危险工具 → 阻断
    if is_sec and dispatch.get("mode","") not in ("swarm","solo") and TOOL in {"Bash","Write","Edit","WebSearch","WebFetch","Agent"}:
        mand = "1. 跑brain: python ~/.claude/scripts/hive-brain.py --target '<任务>'\n2. brain选好Agent再动手"
        mandate(mand)
        print(f"BLOCKED: {TOOL} 安全场景没跑brain", file=sys.stderr)
        sys.exit(2)

    # FINDING WRITEBACK: 攻击跑了+没写发现 → 阻断Bash
    if TOOL == "Bash" and s.get("attack_ran") and not s.get("finding_wrote"):
        mandate("你刚才攻击跑完了没写发现回hive-mind。先写: python ~/.claude/scripts/hive-mind.py write <agent> --finding --type <T> --severity <S> --endpoint <EP>")
        print("BLOCKED: findings not written back", file=sys.stderr)
        sys.exit(2)

    sys.exit(0)

# ── PostToolUse: 计数+写flag ──
def post():
    s = ld(STATE) or {"bash_count":0,"pi_warn":0,"hive_miss":0,"attack_ran":False,"finding_wrote":False,"last_ts":""}
    now = datetime.now(TZ)

    if TOOL == "Bash":
        s["bash_count"] += 1
        s["pi_warn"] += 1
        s["attack_ran"] = True
    else:
        s["attack_ran"] = False

    # 检测hive写入
    hive = ld(HIVE_MIND)
    if hive and len(hive.get("findings",[])) > s.get("last_finding_count", 0):
        s["finding_wrote"] = True
        s["attack_ran"] = False
        s["last_finding_count"] = len(hive.get("findings",[]))

    # 重置计数器 (30秒窗口已过)
    prev = s.get("last_ts","")
    if prev:
        try:
            pt = datetime.fromisoformat(prev)
            if (now - pt).total_seconds() > 60:
                s["pi_warn"] = 0
        except: pass

    s["last_ts"] = now.isoformat()
    sv(STATE, s)
    sys.exit(0)

if __name__ == "__main__":
    if "--pre" in sys.argv: pre()
    else: post()
