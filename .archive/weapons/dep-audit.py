#!/usr/bin/env python3
"""依赖审计 — npm audit + CVE 快速检查"""
import json, subprocess, sys, os, argparse

def audit_package_json(path):
    d = os.path.dirname(path)
    try:
        r = subprocess.run(["npm", "audit", "--json"], cwd=d, capture_output=True, text=True, timeout=60)
        data = json.loads(r.stdout)
        vulns = data.get("vulnerabilities", {})
        findings = []
        for name, v in vulns.items():
            for via in v.get("via", []):
                if isinstance(via, dict):
                    findings.append({
                        "package": name, "severity": v.get("severity","?"),
                        "cve": via.get("url","").split("/")[-1] if via.get("url") else "",
                        "title": via.get("title","")[:120],
                        "fix": v.get("fixAvailable", False),
                    })
        return findings
    except Exception as e:
        return [{"error": str(e)}]

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("path", nargs="?", default=".")
    args = p.parse_args()
    pkg = os.path.join(args.path, "package.json")
    if not os.path.exists(pkg):
        print(json.dumps({"error": "no package.json found"}))
        sys.exit(1)
    findings = audit_package_json(pkg)
    critical = sum(1 for f in findings if f.get("severity")=="critical")
    high = sum(1 for f in findings if f.get("severity")=="high")
    print(json.dumps({"total": len(findings), "critical": critical, "high": high, "findings": findings[:20]}, ensure_ascii=False, indent=2))
