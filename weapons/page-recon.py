import urllib.request as u, ssl, re, sys, json
ctx=ssl.create_default_context();ctx.check_hostname=False;ctx.verify_mode=False
B=sys.argv[1]
r=u.urlopen(u.Request(B),timeout=8,context=ctx)
body=r.read().decode()
links=re.findall(r'href=[\"\']([^\"\']+)[\"\']',body)
forms=re.findall(r'action=[\"\']([^\"\']+)[\"\']',body)
comments=re.findall(r'<!--(.*?)-->',body,re.DOTALL)
title=re.findall(r'<title>(.*?)</title>',body)
results={"title":title,"links":links,"forms":forms,"comments":[c.strip()[:100] for c in comments if c.strip()],"size":len(body)}
for p in ["flag","admin","login","register","signup","api","debug","robots.txt",".git/HEAD"]:
    try:
        r2=u.urlopen(u.Request(f"{B}/{p}"),timeout=4,context=ctx)
        results[f"GET /{p}"]=f"{r2.status} ({len(r2.read())}b)"
    except u.HTTPError as e: results[f"GET /{p}"]=str(e.code)
print(json.dumps(results,ensure_ascii=False,indent=2))
