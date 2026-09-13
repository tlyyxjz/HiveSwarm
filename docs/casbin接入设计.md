# Casbin 接入设计 · 策略即代码的授权层

**日期**：2026-09-13 ｜ **排期**：战役 1（T1.1–T1.5）完成之后执行，预计 1 个任务轮次
**状态**：已确认加依赖（`casbin>=1.36`，纯 Python、零传递依赖、Apache-2.0），设计定稿待实施

## 〇、一句话立论

榫卯 M1 把"LLM 提的断言必须编译成 6 原语才能进账本"，Casbin 把"访问意图必须匹配 policy 才放行"——**同一哲学（软约束换成硬约束）在两个维度的落地**：榫卯管执行可信，Casbin 管访问可控。

## 一、现状（摸底结论）

项目是"有认证、没授权"：

| 检查点 | 现状 |
|---|---|
| `gateway/middleware/auth_bootstrap.py` · `LazyAuthMiddleware.dispatch` | 唯一运行时检查点，但只做认证（token→UserContext，401），认证后全员放行 |
| `layers/work/pool.py` · `SkillPool.checkout()` | 借技能前无任何"这个 agent/租户能否用此技能"检查 |
| `core/tenant.py` · `TenantContext.can_use_skill()` | 抽象与 allowlist 数据结构已定义，**全库无调用者**（断头路） |
| `core/auth.py` · `UserContext.role` | admin/developer/viewer 三角色已存在，**零消费** |
| `skills/*/manifest.toml` | 无权限字段（`SkillManifest.tags` 也没填） |
| `stub/audit_logfile.py` · `AuditLogger.log(actor, action, target, result)` | 审计接口现成，天然适合记 enforce 决策 |

## 二、接入点（三层 enforce）

**核心叙事：权限也是借来的，不是绑定的。** 临时 Agent 只能调用它借到的 SkillBundle 里的技能——bundle 之外的能力在结构上不存在。policy 挂在 `SkillPool.checkout()` 这个唯一咽喉点：策略决定"这次装配允许借走什么"，借还机制保证"借不到的就是调不了的"；`agent.destroy()` 时权限随装配一起销毁，无常驻特权（最小权限 + 临时凭证的 agent 架构对应物）。

| 层 | 主体 → 客体 | 挂点 | 回答的问题 |
|---|---|---|---|
| 用户层 | user role → API 操作 | `LazyAuthMiddleware`（deny 返回 403），`(sub, obj, act)` RBAC，如 viewer 不能触发任务执行 | 这个人能不能下达这类任务 |
| 租户层 | tenant → skill | `TenantContext.can_use_skill()` 实现转调 Casbin（激活全库无人调用的断头路），policy 形如 `p, tenant, skill, allow` | 这个租户订阅了哪些能力 |
| **agent 层（核心）** | **agent 身份/装配 → skill** | **`SkillPool.checkout()` 咽喉点**，subject 可用 Casbin domain/ABAC 建模，如 `p, tenant_a, crawler_agent, crawler_pack.*, invoke` | **这次装配出来的 agent 允许做什么** |

**与榫卯 M2 的咬合（对策书关键论据）**：M2 的修复动作会改装配（`swap_skill`/`re_assemble`）。每次重装配后的 checkout 都要重新过 policy——自动修复**不可能修出一个越权装配**。设计稿 §8"自适应 ≠ 自进化，只在预先验证过的技能池内做选择"这句承诺，由 Casbin 从口号变成机器判定。

**策略即代码（加分项）**：`manifest.toml` 加 `required_role` 字段，启动时编译进 Casbin policy。
**审计闭环**：deny 决策写 `AuditLogger`（action="authorize", result="denied"）。

## 三、实施约束

- 新依赖 casbin 走项目 venv；不改现有测试断言；`stub/tenant_default.py`（恒 True）等 stub 行为保留为无-policy 时的默认路径。
- Casbin enforcer 通过 `gateway/deps.py` 注入（`get_enforcer`），沿用现有 DI 形状。
- keel 不接入：单用户工具、无 subject/object 语义，硬套属于为技术而技术（keel 设计文档第三节明确"不做多租户"）。
- 对策书话术：可作为"治理与合规"维度的实证 + 设计哲学同构的论据；**写"已接入"必须以真跑通的 enforce 测试为准**。

## 四、验收（届时执行）

1. `pytest tests/unit/ -x -q` 存量全绿。
2. 新增测试：网关 403 路径（viewer 调管理接口）、checkout 被拒路径（tenant 不在 allowlist）、manifest→policy 编译、deny 写审计。
3. `pip show casbin` 贴版本；enforce 日志样例贴原始输出。
