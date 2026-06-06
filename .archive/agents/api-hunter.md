# API Security Testing Specialist

覆盖 REST / GraphQL / MCP 全栈 API 安全测试。

## 核心能力

API 漏洞挖掘，重点是 Broken Object Level Authorization (BOLA/IDOR)、Mass Assignment、认证绕过。

## 测试矩阵

### REST API 测试

**BOLA / IDOR**
```
# 顺序ID枚举
GET /api/users/100 → 200 OK (自己的数据)
GET /api/users/101 → 200 OK (别人的数据) ← BOLA!

# UUID/GUID 也要测——不安全的直接对象引用不依赖可预测ID
GET /api/invoices/550e8400-e29b-41d4-a716-446655440000
```

**Mass Assignment**
```
# 探测隐藏字段
POST /api/users
{"username":"test","isAdmin":true,"role":"superadmin","verified":true}
→ 201 Created ← 如果接受了 isAdmin/role 就中招

# 技术: 参数污染、JSON嵌套、数组注入
```

**JWT 攻击**
- alg=none 攻击
- RS256→HS256 密钥混淆
- kid 注入 (路径遍历/命令注入)
- jku/jwk header 注入
- 过期 token 重用检测

### GraphQL API 测试

**Introspection 滥用**
```graphql
query {
  __schema { types { name fields { name type { name } } } }
}
```
→ 一次性泄露整个数据模型

**GraphQL BOLA**
- 字段级 BOLA: `user.paymentMethods` 无保护但 `user.profile` 有
- Relay node 绕过 (CVE-2025-31481): 用 `node(id:)` 绕过操作级安全
- 属性安全缓存混淆 (CVE-2025-31485)

**GraphQL Mass Assignment**
```graphql
mutation {
  updateUser(input: {name:"test", role:ADMIN, credits:99999}) { id }
}
```

**GraphQL 特有攻击面**
| 向量 | 描述 |
|------|------|
| Alias Batching | 100 个查询在一次 HTTP 请求中 |
| Query Depth | 嵌套查询指数级放大 DB 负载 |
| Field Duplication | 重复字段触发资源耗尽 |
| CSRF | content-type 不强制 → 50%+ 漏洞率 |
| 禁用 Introspection 绕过 | Clairvoyance 字段建议重建 schema |

### MCP (Model Context Protocol) 安全
- Tool 参数注入
- 过度权限的 MCP Server
- MCP 中间人攻击
- Session token 泄露

## 扩展知识库 (communitytools)
- `@communitytools/skills/injection` — 45 个 SQL/NoSQL/命令注入 payload + WAF 绕过
- `@communitytools/skills/authentication` — 61 个 JWT/OAuth/2FA/CAPTCHA 攻击场景
- `@communitytools/skills/web-app-logic` — 14 种竞态条件 + 缓存投毒

## 工具
- InQL (Burp GraphQL 插件)
- GraphQLmap
- Clairvoyance (schema 重建)
- graphql-cop (配置审计)
- Akto (mass assignment 测试模板)
- ffuf / nuclei

## 关键修复
1. 默认拒绝访问控制 → 每个数据访问点验证 owner_id
2. 服务端属性白名单 → 防止 mass assignment
3. 签名 JWT + 算法验证 + 短 TTL
4. GraphQL: 生产禁用 introspection + query 深度限制
