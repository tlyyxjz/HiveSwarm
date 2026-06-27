# HiveSwarm 明天 3-4h 执行计划 (MiniMax M3 方法论)

**日期**: 2026-06-26
**时长**: 3-4 小时
**方法论**: MiniMax M3 — 时间盒、攻击点排序、每阶段验证、不准做清单

---

## 当前基线 (诚实版)

- ✅ 202 测试 1.5s 全绿
- ✅ FastAPI 网关 5 端点可用 (未经压力测试)
- ✅ Gradio 战情看板 5 面板 (静态度,无实时刷新)
- ✅ agentvet_pack L1-L4 技能包 (能 import,真扫描 372 秒)
- ❌ **网关零鉴权** — 谁调都行,生产环境直接裸奔
- ❌ **SSE 内存泄漏** — subscribe 后永不 unsubscribe
- ❌ **端到端链未验证** — agentvet → gateway → dashboard 没跑通过
- ❌ **Docker 零存在** — 没有 Dockerfile/镜像
- ❌ **4 个空壳文件** — 纯占位,没有任何代码
- ❌ **CHANGELOG 停在 Day 5** — 今天干了这么多一个字没记

---

## 4 个攻击点 (按对交付物影响力排序)

| 攻击点 | 影响 | 代码量 | 风险 |
|--------|------|--------|------|
| **端到端链打通** | 🔥🔥🔥🔥🔥 | 中 (修集成bug) | 中 |
| **安全基线 (鉴权+输入校验)** | 🔥🔥🔥🔥 | 小 (中间件) | 低 |
| **Docker 化** | 🔥🔥🔥🔥 | 小 (Dockerfile+docker-compose) | 低 |
| **质量收尾 (SSE/DI/CHANGELOG)** | 🔥🔥🔥 | 小 | 低 |

---

## 时间线

```
08:00 ── 阶段0: 状态加载 (5 分钟) ──
│   读 ACTIVE_KB.md / 跑 pytest 确认基线
│   验证: 202 passed, 无 regression
│
08:05 ── 阶段1: 安全基线 (45 分钟) ──
│   1a. Gateway 鉴权中间件 (Bearer Token / SimpleAuth 已有)
│       - middleware/auth.py: 从 Authorization header 提取 token
│       - 调 services.auth.check_token(token)
│       - 无 token → 401, token 错 → 403
│       - health 端点豁免鉴权
│   1b. 输入校验加固
│       - TaskRequest.request 不能为空字符串
│       - target 路径白名单校验 (防路径遍历)
│       - task_id 格式校验 (防注入)
│   验证: curl 无 token → 401, 有 token → 200
│
08:50 ── 阶段2: 端到端链打通 (60 分钟) ──
│   2a. 验证 agentvet → HiveSwarm 链路
│       - 启动 gateway (uvicorn)
│       - POST /tasks {"request": "扫描项目", "target": "/tmp/demo/"}
│       - 确认 agentvet L1-L4 skills 被 borrow/run/return
│       - 确认结果写入 MemoryStore
│   2b. 验证 gateway → dashboard 链路
│       - 启动 Gradio dashboard (po 到 gateway)
│       - 在 dashboard 提交任务 → 查看技能池面板更新
│       - 查看事件流面板有 recent events
│   2c. 修集成 bug (如果端到端断裂)
│       - 最可能断点: skill_registry → gateway import 路径
│       - 次可能: pool 未初始化 (TestClient 不触发 lifespan)
│   验证: 一条 "扫描项目" 请求从 gateway 进 → agentvet 跑 → dashboard 能看到结果
│
09:50 ── 阶段3: Docker 化 (45 分钟) ──
│   3a. Dockerfile (多阶段, Python 3.13-slim)
│       - 安装依赖
│       - COPY 源码
│       - EXPOSE 8000 7860
│       - CMD 同时启动 gateway + dashboard
│   3b. docker-compose.yml
│       - hive-gateway: 主服务, 8000 端口
│       - hive-dashboard: Gradio, 7860 端口
│       - hive-memory: SQLite volume 挂载
│   3c. .dockerignore (排除 __pycache__/.git/tests)
│   验证: docker compose up → curl /health 返回 ok
│
10:35 ── 阶段4: 质量收尾 (35 分钟) ──
│   4a. SSE 取消订阅 — 生成器捕获 CancelledError → 遍历 unsub
│   4b. gateway/routes 改用 Depends + 正经 DI
│   4c. CHANGELOG 更新 (写今天改了啥)
│   4d. README 更新 (Day 6-10 状态更新, 测试数更新)
│   验证: pytest 全绿, CHANGELOG 有今天的内容
│
11:10 ── 阶段5: 端到端验证 (20 分钟) ──
│   - pytest 全量
│   - docker compose up 端到端
│   - curl /health /skills /tasks
│   - 检查无死 import/无 TODO/无硬编码路径
│
11:30 完成
```

---

## 不准做

- ❌ 不碰 agentvet 源码 (在 Desktop/agentvet/, 不改它)
- ❌ 不实现 crawler_pack/ppt_pack (3-4h 不够, 另排)
- ❌ 不写新 ABC 接口 (加中间件不意味着加新核心接口)
- ❌ 不做 websocket 替换 SSE
- ❌ 不写 Kubernetes/Helm (过杀, Docker 足矣)
- ❌ 不重构已有代码 (Karpathy 纪律: 手术级改动)
- ❌ 不在 gateway 里加 WebSocket 支持

---

## 每阶段验证门禁

| 阶段 | 验证项 | 不通过 = 不进入下一阶段 |
|------|--------|------------------------|
| 0 | 202 passed | 修 regression |
| 1 | curl 无 token → 401 | 中间件逻辑错误 |
| 2 | agentvet scan 结果存到 memory | skill import 路径断裂 |
| 3 | docker compose up 不炸 | Dockerfile 语法错误 |
| 4 | pytest 全绿 + CHANGELOG 有今天 | 回归/漏记 |
| 5 | 5 个端点全通 + dashboard 可访问 | 任一端点不通过 |

---

## 成果物清单 (明天结束时应该存在的东西)

- [ ] `gateway/middleware/auth.py` — Bearer Token 鉴权中间件
- [ ] `Dockerfile` — 多阶段构建
- [ ] `docker-compose.yml` — 双服务编排
- [ ] `.dockerignore`
- [ ] `docs/CHANGELOG.md` — 更新到今天
- [ ] `README.md` — Day 6-12 状态更新
- [ ] SSE 取消订阅补丁
- [ ] 全部 endpoint 加 Depends DI
- [ ] end-to-end demo 跑通 (agentvet → gateway → dashboard)

---

## 风险清单

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| agentvet scanner 在 Docker 里 import 失败 | 中 | 端到端断 | 先本地验证再打镜像 |
| LiteLLM 依赖过大 → Docker 镜像 > 2GB | 高 | 部署不便 | slim base + --no-cache-dir |
| SSE 取消订阅改动波及 bus.py | 低 | 测试炸 | 只动 routes_events.py |
| Windows 路径问题在 Docker Linux 里炸 | 中 | 启动失败 | 全部改 Path 对象 |