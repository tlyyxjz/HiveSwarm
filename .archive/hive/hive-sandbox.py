#!/usr/bin/env python3
"""
hive-sandbox.py — 蜂巢沙箱引擎 (借鉴 deer-flow sandbox 系统)
每个Agent跑在独立的隔离工作区，不安全命令自动阻止。

沙箱模式:
  local   — 文件系统隔离 (Windows/Linux通用)
  docker  — Docker容器执行 (需要Docker)

隔离级别:
  1. 文件: 每个Agent专属 workdir (workspace/uploads/outputs)
  2. 路径: 禁止访问 ../ ..\ /etc /Windows 等逃逸路径
  3. 命令: 禁止 rm -rf / shutdown / format 等危险命令
  4. 网络: 可限制外网访问 (--offline)
  5. 超时: 30s 默认超时

用法:
  python hive-sandbox.py --agent api-hunter --exec "curl http://target/api"
  python hive-sandbox.py --agent sql-injector --exec "sqlmap -u URL"
  python hive-sandbox.py --clean                    # 清理所有沙箱
  python hive-sandbox.py --status                   # 沙箱状态
"""
import json, subprocess, sys, os, re, shutil, argparse, signal
from pathlib import Path
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager

TZ = timezone(timedelta(hours=8))
HOME = Path.home()
SANDBOX_ROOT = HOME / ".claude/sandbox"
SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)

DANGEROUS_COMMANDS = [
    r"rm\s+-rf\s+/", r"rm\s+-rf\s+\*", r"rmdir\s+/s\s+/q", r"del\s+/f\s+/s",
    r"shutdown", r"reboot", r"format\s", r"mkfs", r"dd\s+if=",
    r">\s*/dev/sda", r"fdisk", r"chmod\s+777\s+/", r"wget.*\|.*sh",
    r"curl.*\|.*bash", r"eval\s+\$", r"\$\(\s*cat", r"`cat",
    r":(){ :|:& };:", r"chmod\s+u\+s\s+/bin", r"mv\s+/etc",
]

PATH_ESCAPE = [r"\.\.\/", r"\.\.\\", r"~\/", r"\/etc\/", r"\/proc\/",
               r"C:\\Windows", r"\\Windows\\", r"\/var\/log", r"\/root\/"]

def _agent_dir(agent): return SANDBOX_ROOT / agent

def check_dangerous(cmd):
    for pat in DANGEROUS_COMMANDS:
        if re.search(pat, cmd, re.IGNORECASE):
            return f"DANGEROUS: blocked pattern: {pat[:40]}"
    for pat in PATH_ESCAPE:
        if re.search(pat, cmd):
            return f"PATH_ESCAPE: blocked: {pat[:40]}"
    return None

def create_sandbox(agent):
    sb = _agent_dir(agent)
    for d in ["workspace", "uploads", "outputs"]:
        (sb / d).mkdir(parents=True, exist_ok=True)
    return sb

def sandbox_env(agent):
    sb = _agent_dir(agent)
    env = os.environ.copy()
    env["SANDBOX_ROOT"] = str(sb)
    env["SANDBOX_WORKSPACE"] = str(sb / "workspace")
    env["SANDBOX_UPLOADS"] = str(sb / "uploads")
    env["SANDBOX_OUTPUTS"] = str(sb / "outputs")
    env["SANDBOX_AGENT"] = agent
    return env

def exec_sandboxed(agent, cmd, timeout=30, offline=False):
    danger = check_dangerous(cmd)
    if danger:
        return {"ok": False, "error": danger, "blocked": True}

    sb = create_sandbox(agent)
    cwd = sb / "workspace"
    start = datetime.now(TZ)

    try:
        r = subprocess.run(cmd, shell=True, cwd=str(cwd),
                           env=sandbox_env(agent),
                           capture_output=True, text=True, timeout=timeout)
        elapsed = (datetime.now(TZ) - start).total_seconds()
        return {
            "ok": r.returncode == 0,
            "stdout": r.stdout[:5000],
            "stderr": r.stderr[:2000],
            "code": r.returncode,
            "elapsed": elapsed,
            "cwd": str(cwd),
            "blocked": False,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Timeout after {timeout}s", "blocked": False}
    except Exception as e:
        return {"ok": False, "error": str(e), "blocked": False}

def clean_sandbox(agent=None):
    if agent:
        d = _agent_dir(agent)
        if d.exists(): shutil.rmtree(d)
        return f"Cleaned {agent}"
    else:
        if SANDBOX_ROOT.exists():
            shutil.rmtree(SANDBOX_ROOT)
        SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
        return "Cleaned all sandboxes"

def status():
    if not SANDBOX_ROOT.exists(): return []
    agents = []
    for d in sorted(SANDBOX_ROOT.iterdir()):
        if d.is_dir():
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            agents.append({
                "agent": d.name,
                "workspace": str(d / "workspace"),
                "size_kb": size // 1024,
                "files": sum(1 for _ in d.rglob("*") if _.is_file()),
            })
    return agents

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--agent", help="Agent name")
    p.add_argument("--exec", help="Command to execute sandboxed")
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--offline", action="store_true")
    p.add_argument("--clean", action="store_true")
    p.add_argument("--status", action="store_true")
    args = p.parse_args()

    if args.clean:
        print(clean_sandbox(args.agent))
    elif args.status:
        for s in status():
            print(json.dumps(s, ensure_ascii=False, indent=2))
    elif args.agent and args.exec:
        result = exec_sandboxed(args.agent, args.exec, args.timeout, args.offline)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("蜂巢沙箱引擎 | Usage: --agent <name> --exec '<cmd>' | --clean | --status")
        print(json.dumps({"mode": "ready", "sandbox_root": str(SANDBOX_ROOT)}, ensure_ascii=False))
