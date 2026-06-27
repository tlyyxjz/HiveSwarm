# VISION — HiveSwarm 是什么

## 1. 一句话定位

**HiveSwarm = 一个能让"一堆技能被动态借/还"的多 Agent 框架**,核心创新是 `Skill 不是永久绑在 Agent 上,而是从池子里借出来用,用完还回去`。

## 2. 解决什么问题

### 痛点:Skills 太多时
- **AutoGen / CrewAI 的问题**: 技能是 Agent 永久属性,任务一多 Agent 数量爆炸,资源不释放,跑久了 OOM
- **我们的方案**: 任务来 → 大脑拆 → 工厂**临时**借 1-3 个 skill 装个 Agent → 跑完 → **销毁 Agent + 还 skill** → 下一个

### 真实场景
- 用户说"帮我做一个 PPT" → Brain 拆成 4 个 subtask(数据/大纲/排版/导出) → 4 个临时 Agent 接力,每个只用一次
- 用户说"扫描这个项目" → Brain 拆 L1-L4 → 4 个临时 Agent 串行,跑完即丢
- 用户说"做一个竞品分析" → Brain 临时决定要 crawl + analyze + summary → 3 个 Agent 跑完就完

## 3. 核心差异 vs 同行

| 维度 | AutoGen / CrewAI | HiveSwarm |
|---|---|---|
| 技能绑定 | 永久 | **借/还** |
| Agent 生命周期 | 长寿命 | **临时** |
| 资源管理 | 手动 | **自动 refcount** |
| 失败恢复 | 自己实现 | **策略表配置驱动** |
| 公司化 | 重写 | **改 1 行配置** |

## 4. 适用人群

### MVP 阶段(现在)
- 蜂巢项目开发者(就是三玖自己)
- 想试"借还 + 临时 Agent"思路的工程师
- 学习多 Agent 系统的学生/新人(代码 3000 行,模块清晰)

### 公司化阶段(未来)
- **.公司 内部工具团队**: 让"做 PPT / 写文档 / 跑数据"这些任务自动化
- **SaaS 产品**: 多租户 + 计费 + 审计(11 个接口 ABC 已经预留)
- **科研 / 评测**: 不同模型/策略可替换(走 ABC)

## 5. 6 层架构(一句话版)

```
大脑(拆任务) → 工厂(借技能+装) → 工作(跑)
                ↑                       ↓
              监察(记) ← 修补(失败重调度) ← 检查(过没过)
                ↓                       ↑
                └── 记忆(存) ──────────┘
```

## 6. 现在能跑什么

```bash
$ python -m src.main "帮我做一个 PPT"

Task ID: mock-xxxx
Rationale: mock brain (no LLM key configured)
Subtasks (4): s1, s2, s3, s4
Result: [OK] all passed
  [OK] s1
  [OK] s2
  [OK] s3
  [OK] s4
```

没 LLM key 也能跑(MockBrain 降级)。

## 7. 升级路径(无重写)

每个核心模块都是 ABC,公司化时:
```toml
# config/production.toml
[auth]
provider = "company.oauth_sso"   # 改 1 行

[audit]
provider = "company.kafka_audit"  # 改 1 行
```

**核心代码 0 修改**,只加新 stub + 改 config。详见 `docs/HOW_TO_REPLACE.md`(待写)。

## 8. 12 天路线图

| Day | 内容 | 状态 |
|---|---|---|
| 1-5 | 6 层骨架 + skill 借还 + brain + work + inspect + repair + monitor + memory | ✅ |
| 6-8 | Gradio 看板 / 时间旅行 / pause point / e2e demo | 进行中 |
| 9-10 | 公司模块 stub (auth/audit/billing/tenant/gateway/sdk) | 计划 |
| 11-12 | 完整文档 (ARCH / INTERFACES / HOW_TO_REPLACE) | 计划 |
