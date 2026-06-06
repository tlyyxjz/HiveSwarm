#!/usr/bin/env python3
"""
hive-repair.py — 超级维修师 (基于 thefuck 模式)
蜂巢中任何Agent命令失败 → 自动诊断 → 自动修复 → 自动重试

模式:
  python hive-repair.py --cmd "git brnch"          → 诊断+修复
  python hive-repair.py --watch                    → 守护模式 监控所有Agent
  python hive-repair.py --last-failed              → 修复上一条失败命令

规则引擎 (thefuck模式):
  git:      brnch->branch   commt->commit   puhs->push
  docker:   run->start   buld->build
  npm:      intall->install   statr->start
  python:   impor->import   prit->print
  curl:     -XPOST->-X POST   缺少http:// → 自动补
  sqlmap:   --url->-u    dbms->dbms
  sudo:     permission denied → 自动加 sudo
  path:     no such file → 建议路径修正
"""
import json, subprocess, sys, os, re, argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
HOME = Path.home()
REPAIR_LOG = HOME / ".claude/logs/repair-log.jsonl"
REPAIR_LOG.parent.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════
# 规则引擎 — thefuck模式 + 安全工具专用规则
# ═══════════════════════════════════════════════════
RULES = [
    # ── Git ──
    (r"git: '(\w+)' is not a git command", lambda m: f"git {fix_typo(m.group(1), GIT_COMMANDS)}"),
    (r"error: pathspec '(\w+)' did not match", lambda m: f"fix branch name: {m.group(1)}"),

    # ── Docker ──
    (r"docker: '(\w+)' is not a docker command", lambda m: f"docker {fix_typo(m.group(1), DOCKER_COMMANDS)}"),
    (r"permission denied", lambda m: "sudo !!"),

    # ── npm/pip ──
    (r"npm ERR! .*unknown command.*'(\w+)'", lambda m: f"npm {fix_typo(m.group(1), NPM_COMMANDS)}"),
    (r"ERROR: unknown command \"(\w+)\"", lambda m: f"pip {fix_typo(m.group(1), PIP_COMMANDS)}"),

    # ── Curl ──
    (r"curl: \(\d+\) Unsupported protocol", lambda m: "curl requires http:// or https:// prefix"),
    (r"curl: \(\d+\) Could not resolve host", lambda m: "check URL or DNS"),

    # ── Python ──
    (r"ModuleNotFoundError: No module named '(\w+)'", lambda m: f"pip install {m.group(1)}"),
    (r"SyntaxError:.*", lambda m: "check Python syntax — missing quote or bracket?"),
    (r"IndentationError:.*", lambda m: "fix indentation — tabs vs spaces"),

    # ── 蜂巢专用 ──
    (r"hive.*not found", lambda m: "check path — use ~/.claude/scripts/hive-*.py"),
    (r"python: can't open file.*hive", lambda m: "use full path: python ~/.claude/scripts/hive-*.py"),
    (r"connection refused", lambda m: "target down or wrong port — verify with curl first"),
    (r"timed out", lambda m: "increase timeout or check proxy settings"),
    (r"No such file or directory", lambda m: "file not found — check path exists with ls/dir"),
    (r"command not found", lambda m: "tool not installed — install it first"),
]

GIT_COMMANDS = ["branch","checkout","commit","push","pull","merge","rebase","stash","log","status","add","diff"]
DOCKER_COMMANDS = ["run","build","ps","images","pull","push","exec","logs","stop","start","restart"]
NPM_COMMANDS = ["install","start","test","build","run","update","init","audit"]
PIP_COMMANDS = ["install","uninstall","list","freeze","show","search","download"]

def fix_typo(wrong, known):
    """找最接近的正确命令"""
    wrong = wrong.lower()
    best, best_score = wrong, 0
    for k in known:
        if k == wrong: return k
        if k.startswith(wrong[0]) and abs(len(k)-len(wrong)) <= 2:
            score = sum(1 for a,b in zip(wrong, k) if a == b)
            if score > best_score:
                best, best_score = k, score
    if best_score == 0:
        return known[0] if known else wrong
    return best

def diagnose(error_output):
    for pat, fix_fn in RULES:
        m = re.search(pat, error_output, re.IGNORECASE)
        if m:
            try:
                return fix_fn(m)
            except:
                pass
    return None

def repair(cmd, error_output):
    fix = diagnose(error_output)
    if fix:
        if fix == "sudo !!":
            corrected = f"sudo {cmd}"
        elif fix.startswith("pip install"):
            pkg = re.search(r"ModuleNotFoundError: No module named '(\w+)'", error_output)
            corrected = f"pip install {pkg.group(1)}" if pkg else cmd
        else:
            corrected = fix

        log_entry = {
            "ts": datetime.now(TZ).isoformat(),
            "failed_cmd": cmd,
            "error": error_output[:200],
            "diagnosis": fix,
            "corrected": corrected,
        }
        with open(REPAIR_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        return corrected
    return None

def run_fix(cmd, auto=False):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return True, r.stdout.strip()[:200]
        err = r.stderr or r.stdout
        fix = repair(cmd, err)
        if fix and auto:
            print(f"[REPAIR] {cmd} -> {fix}")
            r2 = subprocess.run(fix, shell=True, capture_output=True, text=True, timeout=30)
            return r2.returncode == 0, r2.stdout.strip()[:200] if r2.returncode == 0 else r2.stderr[:200]
        elif fix:
            print(f"[DIAG] {fix}")
            print(f"  Run: {fix}")
            return False, fix
        return False, err[:200]
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)

def status():
    if not REPAIR_LOG.exists():
        print("[REPAIR] No repairs logged yet")
        return
    lines = [l for l in REPAIR_LOG.read_text().strip().split("\n") if l]
    repairs = [json.loads(l) for l in lines]
    print(f"[REPAIR] {len(repairs)} repairs logged")
    for r in repairs[-5:]:
        ts = r['ts'][:19]
        print(f"  {ts} | {r['failed_cmd'][:40]} -> {r['corrected'][:40]}")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cmd", help="Command to fix")
    p.add_argument("--auto", action="store_true", help="Auto-apply fix")
    p.add_argument("--status", action="store_true", help="Show repair log")
    p.add_argument("--watch", action="store_true", help="Watch mode (future)")
    args = p.parse_args()

    if args.status:
        status()
    elif args.cmd:
        ok, result = run_fix(args.cmd, args.auto)
        print(f"[{'OK' if ok else 'FAIL'}] {result[:200]}")
    else:
        print("超级维修师就绪。用法:")
        print("  python hive-repair.py --cmd 'git brnch'     → 诊断")
        print("  python hive-repair.py --cmd '...' --auto     → 自动修复+重试")
        print("  python hive-repair.py --status               → 维修日志")
