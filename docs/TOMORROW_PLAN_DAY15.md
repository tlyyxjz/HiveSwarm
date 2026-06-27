# HiveSwarm Day 15 计划 (MiniMax M3 方法论)

**日期**: 2026-06-28
**时长**: 3-4 小时
**方法论**: MiniMax M3

---

## 当前基线 (诚实版)

> 5/27 18:17 实际验证 (pytest + wc -l + git status)

- ✅ **245 passed, 3 skipped** — Ollama 集成测试因服务不可达被 skip（不是 fail）
- ✅ Ollama 接入：`stub/llm_providers.py` + `stub/llm_litellm.py` 配置驱动 dispatch
- ✅ Gateway 5 端点 + Bearer Token 鉴权 + 输入校验
- ✅ Docker 化（Dockerfile + docker-compose.yml + .dockerignore）
- ✅ SSE 取消订阅修复
- ✅ Gradio 战情看板
- ✅ 3 个 Skill Pack：agentvet_pack / crawler_pack / ppt_pack
- ✅ `docs/HOW_TO_REPLACE.md` 已存在 **409 行**（含 OAuth/Kafka/Stripe/Qdrant/OTel 5 个场景示例）— **不是未写**
- ⚠️ **git 仍空仓库**：No commits yet on main — 必须 Day 15 第一件事先做初始 commit
- ⚠️ **CHANGELOG 0.2.0 已存在**（2026-06-26，209 测试基线）— 当前已 245 需补 v0.2.0 patch 段
- ❌ 公司化 stub 仅 `auth_simple.py` / `audit_logfile.py` / `billing_noop.py` / `recovery_retry.py` / `tenant_default.py` / `telemetry_noop.py` 6 个占位 — Kafka/Stripe/OTel/Circuit-breaker 无真实替换 stub 文件
- ❌ 没有 GitHub Release v0.2.0 — code + tag + release notes 缺
- ❌ OpenAPI SDK 未对外发布 — `sdk/hiveswarm_client/` 仓里有但缺 README
- ❌ 端到端 docker compose up 未真跑过 — Windows 无 WSL，DOCKER_SKIP 标记

**基线修正**：任务描述的 "246 passed" 应为 **245 passed + 3 skipped**；HOW_TO_REPLACE.md 不是空白，是 409 行含 5 场景示例。

---

## 3 个攻击点 (按"卖给别人"影响力排序)

| 攻击点 | 影响 | 代码量 | 风险 |
|--------|------|--------|------|
| **git 首提交 + CHANGELOG v0.2.0 补 245 条基线 + 6 公司化 stub 文件补齐** | 🔥🔥🔥🔥🔥 | 中 (~150 行 × 6 stub) | 中 |
| **HOW_TO_REPLACE.md 扩到 11 ABC 覆盖（当前 5）** | 🔥🔥🔥🔥 | 中 (~150 行新增) | 低 |
| **GitHub Release v0.2.0** | 🔥🔥🔥 | 小 (git tag + gh release) | 低 |

---

## 时间线

```
08:00 ── 阶段0: 状态加载 + git 首提交 (15 分钟) ──
│   0a. pytest 验证基线 (期望 245 passed + 3 skipped)
│   0b. 五关门禁快速复测（DRY/异常/线程/资源/验证）
│   0c. git add . && git commit -m "chore: Day 14 baseline snapshot (245 passed)"
│       ⚠️ 首次提交须排除 backup/ (已在 .gitignore)
│   验证: 245 passed + git log --oneline 有 1 条 commit
│
08:15 ── 阶段1: 公司化 stub 6 个真实替换文件 (110 分钟) ──
│   1a. stub/auth_oauth.py — OAuth2 + JWT/JWKS (扩展 HOW_TO_REPLACE 场景 1 代码)
│       - 单测：3 条 (token 颁发 / refresh / 过期)
│   1b. stub/audit_kafka.py — confluent_kafka.Producer (TYPE_CHECKING 软依赖)
│       - 单测：3 条 (JSONL 序列化 / 异常降级 / 缓冲 flush)
│   1c. stub/billing_stripe.py — stripe.Charge 按 token 计量
│       - 单测：3 条 (正常计费 / 余额不足 / 重试)
│   1d. stub/tenant_multi.py — 租户隔离 (Lock 保护)
│       - 单测：3 条 (A 不可读 B / 切换租户 / 跨租户抛异常)
│   1e. stub/observability_otel.py — OpenTelemetry Tracer
│       - 单测：3 条 (span 创建 / context 传播 / 异常标记)
│   1f. stub/recovery_circuit.py — CircuitBreaker (Lock 保护)
│       - 单测：3 条 (正常 / 失败 N 次熔断 / 半开恢复)
│   验证: 6 stub × 3 单测 = 18 条新测试全绿；pytest 总数 263 passed
│
10:05 ── 阶段2: HOW_TO_REPLACE.md 扩到 11 ABC 覆盖 (50 分钟) ──
│   2a. 新增 6 场景：Store/Governance/Memory/EventBus/SkillPool/Brain
│   2b. 每个场景：原 config + 新 config + diff + 验证步骤（< 30 行）
│   2c. 不重复 ARCH.md / INTERFACES.md — 链接引用
│   验证: HOW_TO_REPLACE.md < 600 行；11 ABC 全覆盖
│
10:55 ── 阶段3: CHANGELOG v0.2.0 patch + Release v0.2.0 (40 分钟) ──
│   3a. CHANGELOG.md 补 v0.2.0 patch 段（245 基线 + 6 stub）
│   3b. git tag v0.2.0 -m "v0.2.0: 6 公司化 stub + 11 ABC 替换文档"
│   3c. gh release create v0.2.0 --title "v0.2.0" --notes-file docs/RELEASE_NOTES_v0.2.0.md
│   3d. git push origin main --tags
│   验证: gh release view v0.2.0 可达 + tag 同步
│
11:35 ── 阶段4: 端到端验证 (10 分钟) ──
│   - pytest 全量 (期望 263 passed + 3 skipped)
│   - 6 stub smoke test (mock 跑通)
│   - gh release 页 URL 截图存档
│   验证: 五关门禁复测全过
│
11:45 完成
```

---

## 不准做

- ❌ 不实现真实 OAuth/Kafka/Stripe 服务调用（mock + TYPE_CHECKING 软依赖）
- ❌ 不写 Kubernetes/Helm（过杀）
- ❌ 不重构 core/ 13 ABC 接口（签名冻结）
- ❌ 不动 gateway / dashboard / skills/agentvet_pack 等已稳定模块
- ❌ 不写 README Day 16+ 状态（Day 16 计划再写）
- ❌ 不加新 ABC 接口
- ❌ 不删 backup/ 目录（已在 .gitignore，保留历史）

---

## 每阶段验证门禁

| 阶段 | 验证项 | 不通过 = 不进入下一阶段 |
|------|--------|------------------------|
| 0 | 245 passed + 3 skipped + git log ≥ 1 commit | 修 regression / git 配错 |
| 1 | 6 stub × 3 单测全绿 | 单测逻辑错 |
| 2 | HOW_TO_REPLACE.md < 600 行 + 11 ABC 全覆盖 | 文档爆炸 |
| 3 | gh release URL 可达 + tag 同步 | tag/release 流程错 |
| 4 | 263 passed + 3 skipped + smoke test 全通 | 任意失败 |

---

## 风险清单

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| confluent_kafka / stripe / PyJWT 未装 | 高 | stub import 失败 | TYPE_CHECKING 延迟 import + try/except ImportError |
| gh CLI 未登录 | 高 | release 失败 | 提前 `gh auth status` 检查 |
| git 空仓首次提交冲突 | 中 | 阶段 0 卡住 | 阶段 0 先 commit，阶段 3 再 tag |
| HOW_TO_REPLACE.md 6 新场景超 30 行 | 中 | 文档失焦 | 每个场景 < 30 行 + 链接引用现有 ARCH |
| Ollama 3 skip 测试不是 pass | 低 | 总数对不上 | 接受 263 + 3 skipped，不强求 |

---

## 成果物清单 (Day 15 结束时应该存在的东西)

- [ ] git 首次 commit (Day 14 snapshot)
- [ ] `stub/auth_oauth.py` + 单测 3 条
- [ ] `stub/audit_kafka.py` + 单测 3 条
- [ ] `stub/billing_stripe.py` + 单测 3 条
- [ ] `stub/tenant_multi.py` + 单测 3 条
- [ ] `stub/observability_otel.py` + 单测 3 条
- [ ] `stub/recovery_circuit.py` + 单测 3 条
- [ ] `docs/HOW_TO_REPLACE.md` < 600 行 + 11 ABC 全覆盖
- [ ] `CHANGELOG.md` v0.2.0 patch 段补完
- [ ] `docs/RELEASE_NOTES_v0.2.0.md` 填充实际内容
- [ ] `git tag v0.2.0`
- [ ] `gh release v0.2.0` 页面

---

## 五关门禁（验证前必过）

### 关 1 DRY
- 不重复 Day 14 计划的 5 阶段结构模板（改用 3 攻击点 + 4 阶段）
- HOW_TO_REPLACE.md 不重复 ARCH.md / INTERFACES.md（链接引用）

### 关 2 异常
- 6 stub 示例代码用 `try/except`，加 `logger.warning(..., exc_info=True)`（至少 1 处）

### 关 3 线程
- tenant_multi.py / recovery_circuit.py 用 threading.Lock 保护共享状态

### 关 4 资源
- confluent_kafka / stripe / PyJWT 用 TYPE_CHECKING 延迟 import（不强制装）
- wc -l docs/TOMORROW_PLAN_DAY15.md < 200 行
- wc -l docs/RELEASE_NOTES_v0.2.0.md < 100 行

### 关 5 验证
- 时间盒总和 3h45m ≤ 4h（阶段 0+1+2+3+4 = 15+110+50+40+10 = 225 分钟）
- 6 stub 文件存在占位（day15-exec Agent 填充实际代码）

---

## 不准做清单（Karpathy 纪律）

- ❌ 不实现真实 OAuth/Kafka/Stripe（只用 mock + TYPE_CHECKING）
- ❌ 不重构 core/ 13 ABC
- ❌ 不写 README Day 16+ 状态
- ❌ 不加新 ABC
- ❌ 不删 backup/ 目录
- ❌ 不预测未来 Day 16-30（写完 15 就停）

---

## 充分利用 Ollama 原则

- 计划文档本应让 Ollama 起草，但本会话 Ollama 僵死（test_ollama_e2e 3 条 skipped）→ 退到主线程写
- 未来 Day 15 执行时：6 stub 示例代码让 Ollama 起草（主线程 curl），主线程校 + 集成测试

---

## 完成后回报

1. 五关门禁验证命令输出
2. 实际 wc -l / pytest 总数 / git log --oneline
3. 任何妥协说明（基线 245 而非 246、HOW_TO_REPLACE 已存在等）