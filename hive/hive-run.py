#!/usr/bin/env python3
"""Agent可执行入口 — 匹配到谁就自动跑谁的武器"""
import sys, subprocess
WEAPONS = {
    "sql-injector":    "python ~/.claude/scripts/inject-probe.py",
    "xss-hunter":      "python ~/.claude/scripts/inject-probe.py",
    "http-smuggler":   "python ~/.claude/scripts/smuggler-probe.py",
    "api-hunter":      "python ~/.claude/scripts/api-probe.py",
    "supply-chain":    "python ~/.claude/scripts/dep-audit.py",
    "binary-exploiter":"python ~/.claude/scripts/deser-probe.py",
}
agent = sys.argv[1] if len(sys.argv) > 1 else ""
target = sys.argv[2] if len(sys.argv) > 2 else ""
if agent not in WEAPONS:
    print(f"[AGENT] {agent}: no auto-weapon, use manual methodology from ~/.claude/agents/{agent}.md")
    sys.exit(0)
cmd = f"{WEAPONS[agent]} {target}" if target else WEAPONS[agent]
print(f"[AGENT] {agent} -> {cmd}")
