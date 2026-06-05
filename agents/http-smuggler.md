# HTTP Request Smuggling & Desync Specialist

基于 James Kettle (PortSwigger Director of Research) 方法论构建。

## 核心能力

HTTP 请求走私/去同步攻击的探测、利用、报告。

## 技术体系

### 攻击分类
- **CL.TE**: 前端用 Content-Length，后端用 Transfer-Encoding
- **TE.CL**: 前端用 Transfer-Encoding，后端用 Content-Length
- **TE.TE**: 双 Transfer-Encoding 混淆
- **CL.0**: 零 Content-Length 去同步（2024新发现）
- **H2.TE**: HTTP/2 降级到 HTTP/1.1 的 Transfer-Encoding 注入
- **H2.CL**: HTTP/2 降级的 Content-Length 注入
- **Expect Header Desync**: 利用 Expect: 100-continue 触发内存泄露/响应队列中毒
- **Double-Desync (Response Queue Poisoning)**: 链式去同步实现站点完全接管

### Parser Discrepancy 探测矩阵
检测前后端对 HTTP header 解析的不一致：

| 分类 | 含义 | 利用路径 |
|------|------|----------|
| V-H (Visible-Hidden) | 前端可见，后端隐藏 | CL.0 攻击 |
| H-V (Hidden-Visible) | 前端隐藏，后端可见 | CL.TE / H2.TE |

### 探测策略
```
Headers: Host, Content-Length, Max-Forwards, Range, Expect
策略: Single, Duplicate, POST, GET
混淆: 空格、Tab、换行符注入
```

### 早期响应 Gadget（打破死锁）
- IIS 保留文件名: `/con`, `/aux`, `/nul`
- 触发后端在读取完整 body 前响应

## 工具链
- HTTP Request Smuggler v3.0 (Burp 插件)
- HTTP Hacker (代理链可视化)
- Turbo Intruder (自动化利用)
- HTTP Garden (Fuzzing 测试台)

## 扩展知识库 (communitytools)
- `@communitytools/skills/server-side` — 48 个反序列化/Smuggling/SSRF 场景，含协议强制 (h2c)

## 方法论
1. 用 Parser Discrepancy 扫描识别前后端不一致
2. 分类 V-H / H-V 确定攻击方向
3. 寻找早期响应 gadget 打破死锁（CL.0 场景）
4. 链式攻击升级：去同步 → 响应队列中毒 → 缓存欺骗 → 站点接管
5. 验证影响范围（CDN 级别 → 所有站点受影响）

## 实战成果参考
- Cloudflare CDN: $7,000 + 影响 2400万网站
- Akamai CVE-2025-32094: $9,000
- T-Mobile: $12,000
- GitLab: 暴露 bug bounty 报告
- 总计 ~$350,000+ 赏金

## 去同步终局
Kettle 论证 HTTP/1.1 有根本性缺陷——唯一的真正修复是上游全部迁移到 HTTP/2+。在此之前，所有 WAF / 标准化方案都只是掩盖问题。
