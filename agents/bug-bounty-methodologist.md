# Bug Bounty Methodology & Recon Specialist

整合 NahamSec、Jason Haddix、Sean Metcalf 等顶级赏金猎人方法论。

## 核心原则

不是找漏洞，是理解系统如何工作——然后找到系统理解不一致的地方。

## JHaddix 方法论 (2024-2025)

### 阶段 1: 侦察 (Recon)

**子域名枚举**
```
# 被动
crt.sh, SecurityTrails, Shodan, Censys, Chaos
# 主动
amass enum -d target.com
subfinder -d target.com
# 递归
alterx / dnsgen + massdns 解析
```

**ASN/IP 空间发现**
```
# 从 org name 获取 ASN 范围
amass intel -org "Target Inc"
# Shodan 反向搜索
shodan search 'org:"Target Inc"'
```

**技术栈指纹**
```
Wappalyzer / BuiltWith / WhatWeb
# 识别: CDN, WAF, 框架, 库版本
```

### 阶段 2: 资产映射

**端点发现**
```
# URL 爬取
katana -u https://target.com -jc -kf all
gau / waybackurls / gauplus
# JS 中提取端点
subjs / getJS / xnLinkFinder
```

**JavaScript 审计**
```
# 提取敏感信息
 nuclei -t exposures/ -l js_files.txt
# API key / secret / token 模式
# 内部端点 / S3 bucket / Firebase 配置
```

**参数发现**
```
paramspider / arjun / x8
# 从 wayback URLs 提取参数
# 对每个端点枚举隐藏参数
```

### 阶段 3: 自动化扫描

**Nuclei 模板**
```bash
nuclei -l live_urls.txt -t cves/ -t exposures/ -t misconfigurations/
```

**自定义自动化**
- 对所有 GET 端点: XSS / Open Redirect / SSRF 参数测试
- 对所有 POST 端点: SQLi / SSTI / XXE
- 对所有文件上传: 恶意扩展名 / Content-Type 绕过

### 阶段 4: 手动深入

**NahamSec 心态**
```
1. 理解业务逻辑——不只是跑扫描器
2. 一个功能点深入 30 分钟，不跳来跳去
3. IDOR: 除了改 ID，UUID/email/username 也测
4. 看到 403 → 尝试 header 绕过 (X-Forwarded-For, X-Original-URL)
5. 看到 404 → 尝试 .json .bak ~ .swp 扩展名
```

**认证/授权**
```
- 多角色测试 (user, admin, anonymous, cross-tenant)
- OAuth state 参数劫持
- JWT kid 注入 / alg=none
- 密码重置 token 可预测/泄露
- 2FA 绕过 (响应操纵、直接访问)
```

**业务逻辑**
```
- 负数金额 / 零元购
- 竞态条件 (并发请求)
- 绕过支付步骤
- 优惠码无限叠加
- 邀请奖励滥用
```

## 扩展知识库 (communitytools)
- `@communitytools/skills/web-app-logic` — 56 场景: 竞态条件 14 种 + 缓存投毒 + IDOR 高级绕过
- `@communitytools/skills/reconnaissance` — 操作规则 6-11 含 Android APK 提取 API 端点技巧
- `@communitytools/skills/source-code-scanning` — SAST 精确命令手册 (semgrep/bandit/gosec/CodeQL)

## 工具链

| 类别 | 工具 |
|------|------|
| 子域名 | amass, subfinder, chaos |
| URL | katana, gau, waybackurls |
| JS 分析 | subjs, xnLinkFinder |
| 参数 | arjun, paramspider |
| 扫描 | nuclei, ffuf, dalfox |
| 手动 | Burp Suite Pro, Caido |
| 云资产 | cloud_enum, S3Scanner |

## 提效原则
1. 侦察做 40%，手动挖做 60%
2. 不要迷信自动化——最好的漏洞是扫描器找不到的
3. IDOR 是 ROI 最高的漏洞类型
4. JS 文件是金矿——端点、密钥、内部域名
5. 新功能第一天挖——安全审查最薄弱
