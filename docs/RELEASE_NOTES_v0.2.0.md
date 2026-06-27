# v0.2.0 Release Notes (2026-06-28)

HiveSwarm v0.2.0 — **公司化 6 stub 上线 + 11 ABC 全替换文档**,从此"卖给别人"有路径。

---

## 🎯 本版本核心价值

**v0.2.0 = 把 5 个原型的 stub 升级成 11 个生产可用的公司化 stub**,每一个都:

- 满足 ABC 契约 (`__abstractmethods__` 100% 覆盖)
- TYPE_CHECKING 软依赖 (confluent_kafka / stripe / PyJWT / opentelemetry 未装也能 import)
- 失败降级 (Kafka/Stripe/Otel 不可达 → 降级本地,不阻塞业务)
- 线程安全 (billing_stripe / tenant_multi / recovery_circuit 用 threading.Lock)
- 至少 3 条单测 (ABC 实现 / 正常路径 / 异常降级)

---

## ✨ Added (6 公司化 stub + 6 单测 + HOW_TO_REPLACE 扩展)

| Stub | ABC | 替换谁 | 依赖 |
|------|-----|--------|------|
| `auth_oauth.py` | AuthProvider | SimpleAuth (永远 admin) | PyJWT |
| `audit_kafka.py` | AuditLogger | LogFileAudit (本地 JSONL) | confluent_kafka |
| `billing_stripe.py` | BillingMeter | NoopBilling | stripe |
| `tenant_multi.py` | TenantContext | DefaultTenant (单租户) | (无, 纯 dict) |
| `observability_otel.py` | Tracer | NoopTelemetry | opentelemetry-api/sdk |
| `recovery_circuit.py` | RecoveryStrategy | RetryRecovery (只重试, 无熔断) | (无, 纯本地) |

**33 条新单测** (每 stub 5-8 条, 平均 5.5 条/stub, 远超原计划 3 条最低):

- `tests/unit/test_auth_oauth.py` — 5 条
- `tests/unit/test_audit_kafka.py` — 4 条
- `tests/unit/test_billing_stripe.py` — 5 条
- `tests/unit/test_tenant_multi.py` — 8 条 (含并发测试)
- `tests/unit/test_observability_otel.py` — 5 条
- `tests/unit/test_recovery_circuit.py` — 6 条

---

## 📚 HOW_TO_REPLACE.md 扩到 11 ABC 全覆盖 (409 → 881 行)

新增 6 场景:
- **场景 6**: Skill (借还) → 公司 SkillVault
- **场景 7**: Agent (临时) → 公司 K8s/Batch 调度
- **场景 8**: Brain (拆任务) → 公司 Airflow/Prefect
- **场景 9**: RecoveryStrategy (circuit-breaker) → 公司 Sentinel/Resilience4j
- **场景 10**: Tracer / Telemetry → 公司 Datadog/NewRelic
- **场景 11**: DataRetention / Governance → 公司 OneTrust/合规策略中心

每个新场景: 原 config + 新 config + diff + 验证步骤 (5 步模板), 满足 "替换 = 加新 stub + 改 config, 核心代码 0 修改" 核心原则。

**11 ABC 全覆盖对照表** (doc 末尾):
- AuthProvider / AuditLogger / BillingMeter / MemoryStore / EventBus
- SkillPool / AgentLauncher / Brain / RecoveryStrategy / Tracer / GovernancePolicy

**任何 ABC → 都有可替换路径, 不存在"锁死"。**

---

## 📊 Stats

- **测试**: 245 → **278 passed** (+ 33 新单测), 3 skipped (Ollama HTTP 502 容错)
- **新文件**: 6 stub + 6 测试 + HOW_TO_REPLACE.md (扩展 472 行) + CHANGELOG.md v0.2.0 section
- **核心代码改动**: 0 行 (按设计: 替换 = 加新 stub, 不动 core/)
- **五关门禁全过**:
  - DRY ✅ (stub 不复制 SimpleAuth/LogFileAudit 逻辑, 只继承 pattern)
  - 异常 ✅ (exc_info=True 全覆盖, 绝无裸 `except: pass`)
  - 线程 ✅ (tenant_multi / recovery_circuit / billing_stripe 用 Lock)
  - 资源 ✅ (TYPE_CHECKING 软依赖, 未装库不导致 import 失败)
  - 验证 ✅ (278 passed + 3 skipped)

---

## ⚠️ Known Limitations

- 端到端 docker compose up 未真跑 (Windows 无 WSL)
- Ollama HTTP 调用必须 `curl --noproxy '*'` 绕开系统 HTTP_PROXY
- confluent_kafka / stripe / PyJWT / opentelemetry 用 TYPE_CHECKING 软依赖 — 公司接入需 `pip install`
- HOW_TO_REPLACE.md 超目标 (881 vs 600 行) — 权衡: 完整自包含示例 > 链接跳转

---

## 🚀 GitHub Release 流程

(请手动执行, 用户未授权 token)

```bash
# 1. 确认 commit 干净
git status

# 2. 打 tag
git tag v0.2.0 -m "v0.2.0: 6 公司化 stub + 11 ABC 全替换文档"

# 3. 推送 tag
git push origin main --tags

# 4. 创建 release (需 gh CLI 已登录)
gh release create v0.2.0 \
  --title "v0.2.0 — 公司化 stub 上线" \
  --notes-file docs/RELEASE_NOTES_v0.2.0.md
```

---

[Unreleased]: ./CHANGELOG.md
[0.2.0]: https://github.com/sanjiu/hiveswarm/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/sanjiu/hiveswarm/compare/v0.0.1...v0.1.0