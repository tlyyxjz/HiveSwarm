# HiveSwarm — AI黑客蜂群

**16个安全Agent + 5把自动武器 + 蜂巢共享大脑 = 全自动漏洞猎手**

你说一句话 → hive-brain智能分析 → 自动选出Agent组合 → 并行开火 → 发现汇总hive-mind → 出战报

---

## 安装

```bash
git clone https://github.com/tlyyxjz/HiveSwarm.git
cd HiveSwarm
# 所有文件即开即用，依赖: Python 3.10+
# Agent文件是Markdown，给Claude Code/GPT等AI读
# 自动化脚本是Python，可独立运行
```

## 架构

```
📂 HiveSwarm/
├── hive/           # 🧠 蜂巢核心
│   ├── hive-mind.py        # 共享大脑 — 发现/端点/Agent状态集中存储
│   ├── hive-brain.py       # 智能分析 — 扔报告/描述 → 自动选Agent组合
│   ├── hive-dispatcher.py  # 蜂群调度 — 用户一句话 → 自动派发N个Agent
│   ├── hive-learn.py       # 自学引擎 — 新skill/项目 → 自动提取能力→注册
│   ├── hive-agent.py       # Agent执行器 — 读上下文/写发现/调度下一个
│   └── hive-overseer.py    # 监督者 — 硬阻断违规+强制命令注入
├── agents/         # 🤖 16个安全Agent（Markdown方法论）
│   ├── api-hunter.md       # API/GraphQL/JWT/IDOR/Mass Assignment
│   ├── sql-injector.md     # SQL全谱 Union/Blind/Time/Error/Stacked/OOB
│   ├── xss-hunter.md       # XSS全谱 Reflected/Stored/DOM/mXSS/CSP
│   ├── http-smuggler.md    # HTTP走私 CL.TE/TE.CL/CL.0/H2.TE
│   ├── waf-bypasser.md     # WAF绕过 Cloudflare/AWS/ModSecurity/FortiWeb
│   ├── confusion.md        # 语义混淆 PathTraversal/SSRF/HostHeader
│   ├── race-condition.md   # 竞态/TOCTOU/并发支付
│   ├── supply-chain.md     # 供应链攻击 npm/PyPI/CI-CD
│   ├── binary-exploiter.md # 反序列化RCE/ROP/Heap
│   ├── cloud-escape.md     # 容器逃逸/K8s/AWS
│   ├── mobile-reverser.md  # Android/iOS逆向
│   ├── web3-auditor.md     # 智能合约审计
│   ├── llm-redteamer.md    # LLM攻击 Prompt Injection/RAG
│   ├── ad-pwn.md           # AD域渗透 Kerberos/DCSync
│   ├── bb-methodologist.md # 赏金方法论
│   └── report-humanizer.md # 报告去AI味
├── weapons/        # 🔧 5把自动化探测武器
│   ├── smuggler-probe.py   # HTTP走私 CL.TE/TE.CL/CL.0 一键探测
│   ├── api-probe.py        # API扫描 未授权端点/JWT弱密钥/Mass Assignment/IDOR
│   ├── inject-probe.py     # SQLi+XSS 8种payload自动判别
│   ├── deser-probe.py      # 反序列化RCE node-serialize/pickle/yaml
│   └── dep-audit.py        # npm audit + CVE 依赖检查
└── config/         # ⚙️ 18套组合技预设
    ├── swarm-presets.json  # 16套场景预设 + 5条HackerOne链
    └── agent-skill-matrix.json # Agent-Skill映射矩阵
```

## 快速开始

```bash
# 1. 大脑分析目标
python hive/hive-brain.py --target "Node.js Express JWT API 全面审计"

# 输出: 推荐 5 Agent — api-hunter, sql-injector, binary-exploiter, supply-chain, xss-hunter

# 2. 发起蜂群
python hive/hive-brain.py --target "..." --url https://target.com --execute

# 3. 看战况
python hive/hive-mind.py status

# 4. 现场组队（不依赖预设）
python hive/hive-mind.py swarm --agents "sql-injector,xss-hunter,waf-bypasser" --target "https://x.com"

# 5. 自学新技能
python hive/hive-learn.py --skill ~/.claude/skills/new-tool

# 6. HackerOne链 → 自动生成组合技
python hive/hive-learn.py --chain "SSRF -> Cloud Metadata -> AWS Credential Theft"

# 7. 合规仪表盘
python hive/hive-overseer.py --report
```

## 18套组合技

| 模式 | Agent数 | 触发词 |
|------|--------|--------|
| 🔥 末日全火力 | 16 | 火力全开/全上/倾巢 |
| 🕸️ 蜘蛛女王 | 10 | 全自动/爬全站/全部漏洞 |
| 🕷️ 全面Web审计 | 6 | 全面审计/完整扫描 |
| 💰 SRC赏金狩猎 | 5 | SRC挖洞/HackerOne/补天 |
| ⚡ 快速Web扫描 | 4 | 快扫/扫一下 |
| 💉 注入攻击面 | 4 | 注入扫描 |
| 🔌 API审计 | 3 | API安全/GraphQL审计 |
| ☁️ 云+容器攻击 | 3 | 云安全/容器审计 |
| ⛓️ DeFi安全 | 3 | 智能合约/Web3 |
| 🤖 LLM安全 | 3 | LLM攻击/AI安全 |
| 🏰 AD域渗透 | 3 | AD域/Kerberos |
| 💀 二进制分析 | 3 | 二进制/ROP/Ghidra |
| 📱 移动端审计 | 3 | Android/iOS/APK |
| 📦 供应链审计 | 3 | 供应链/npm/PyPI |
| + 5条HackerOne真实漏洞链自动生成 | 2-3 | XSS->CSRF->ATO / SSRF->云密钥窃取 等 |

## 监督者 — 三层控制

- **硬阻断**: 违规操作 exit(2) 直接停
- **心智覆写**: 写 `#OVERSEER_COMMAND` 强制命令注入
- **合规记录**: `compliance.jsonl` 追踪所有违规

## 省Token铁律

主模型不做搜索/格式化/翻译/grep管道/简单脚本 → 自动检测并阻断，命令派给PI Agent执行

## 许可

MIT License — 随便用，注明出处

## 作者

**三玖的蜂巢黑客团队**

16个AI Agent + 蜂巢大脑，一句话拉满火力全覆盖

GitHub: [tlyyxjz](https://github.com/tlyyxjz)
Blog: [tlyyxjz.github.io](https://tlyyxjz.github.io)
