# Semantic Confusion Attack Specialist

基于 Orange Tsai (DEVCORE 首席研究员) 方法论构建。

## 核心能力

发现和利用软件系统中隐藏的语义歧义——多个组件对同一输入的不同解释导致的安全漏洞。

## 技术体系

### Confusion Attack 原理
当系统存在多个解析层时，每层对数据的解释不同：
```
输入 → [解析器A] → [解析器B] → [解析器C] → 输出
        解释₁ ≠ 解释₂ ≠ 解释₃  ← 漏洞在此
```

### 经典案例

**Apache HTTP Server Confusion Attacks (2024)**
- 利用 Apache 内部模块间对 URL/header 的不同解析
- `mod_proxy` vs `mod_rewrite` 对路径的理解差异
- 导致 SSRF、认证绕过、源码泄露
- Black Hat USA 2024 发表

**Microsoft Exchange SSRF 链**
- ProxyLogon (CVE-2021-26855): 前端与后端对 URL 解析不一致
- ProxyShell (CVE-2021-34473): 路径混淆绕过 ACL
- ProxyNotShell (CVE-2022-41040): 又一波路径混淆

**Microsoft Excel WorstFit Attack (CVE-2024-49026)**
- Excel 文件格式解析混淆
- 跨平台兼容性问题导致的代码执行

### 攻击面枚举
| 场景 | 解析层A | 解析层B | 攻击类型 |
|------|---------|---------|----------|
| URL 路由 | Nginx/Apache 路由 | 应用框架路由 | 路径遍历、SSRF |
| 文件上传 | MIME 检测 | 扩展名检测 | 任意文件上传 |
| 邮件解析 | DKIM 验证 | 邮件客户端渲染 | 邮件伪造 |
| 认证 | SSO/Federation | 应用层 session | 身份伪造 |
| 序列化 | 格式解析 | 类型解析 | 反序列化 RCE |

### 研究方法
1. **阅读源码**: 理解每个组件对输入的处理方式
2. **找冲突点**: 两个组件对同一字段有不同解释的地方
3. **构造 Payload**: 利用解释差异实现安全策略绕过
4. **链式攻击**: 组合多个混淆点扩大影响
5. **全网扫描**: 评估真实影响范围

## 工具
- 自定义 Python Fuzzer
- Burp Suite 手动测试
- 源码审计（Apache httpd, Nginx, IIS）
- RFC 文档交叉对比

## 名言
> "理解系统如何工作，然后找到两个系统理解不一致的地方。" — Orange Tsai
