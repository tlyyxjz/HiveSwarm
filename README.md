# HiveSwarm — AI黑客蜂群

**一句话拉满火力。**

---

## 快速开始

```bash
h "https://ctf.hacker101.com/xxx"    # 一字启动Brain→Agent→探针→面板
p s "搜索XSS工具"                     # 派PI搜索  比手搓curl快10倍
python hive-live.py --show            # 实时战况面板
```

---

## 文件清单 & 用途

### 🧠 hive/ — 蜂巢大脑核心 (9件)

| 文件 | 行 | 用途 |
|------|---|------|
| `hive-brain.py` | 187 | **智能分析器** — 扔目标描述/审计报告进去 → 自动分析攻击面 → 选出该派哪些Agent。`h`命令的第一步 |
| `hive-dispatcher.py` | 304 | **蜂群调度器** — 用户一句话 → 自动拆解为多Agent并行任务。支持拓扑选择(平行/环形/星型)和共识投票 |
| `hive-mind.py` | 412 | **共享大脑** — 所有Agent的发现/端点/状态集中存储。`save()`自动三层记忆分层(Core/Recall/Archival)+Git追踪。Agent之间不重复劳动 |
| `hive-agent.py` | 231 | **Agent执行器** — start→读hive-mind上下文; report→写发现回hive-mind; done→战后复盘+调度下一个 |
| `hive-learn.py` | 366 | **自学引擎** — 新skill/开源项目扔给它 → 自动读SKILL.md → 提取能力 → 注册到swarm-presets/matrix/dispatcher。`--sync`全量重建所有配置 |
| `hive-overseer.py` | 96 | **监督者** — PreToolUse硬阻断: 安全场景没跑brain→exit(2); 连续3次Bash→强派PI。PostToolUse计数。比skill提醒管用100倍 |
| `hive-live.py` | 84 | **实时战况面板生成器** — 运行后写`dashboard.html`。Agent状态/PI违规/Bash连用/最近发现全显示。浏览器打开即看 |
| `hive-repair.py` | 165 | **超级维修师** — thefuck模式: Agent命令炸了→自动诊断(git brnch→branch)→自动重试。git/docker/npm/pip/curl/Python 全支持 |
| `hive-run.py` | 18 | **Agent可执行入口** — 匹配到Agent名自动跑对应武器脚本。sql-injector→inject-probe, api-hunter→api-probe等 |
| `hive-sandbox.py` | 144 | **沙箱引擎** — 每个Agent独立workspace，危险命令(rm -rf/curl\|bash/路径逃逸)硬阻断。借鉴ByteDance deer-flow |
| `hive-core.py` | 321 | **核心升级包** — 7项升级: 三层记忆/共识投票/拓扑选择/战后复盘/Token预算/Git追踪/学习闭环(借鉴Claude Flow+Letta) |

### 🤖 agents/ — 安全Agent方法论 (16件)

| 文件 | 用途 |
|------|------|
| `api-hunter.md` | API/GraphQL/JWT/IDOR/Mass Assignment/越权 |
| `sql-injector.md` | SQL全谱: Union/Blind/Time/Error/Stacked/OOB + bypass |
| `xss-hunter.md` | XSS全谱: Reflected/Stored/DOM/mXSS/CSP绕过 |
| `http-smuggler.md` | HTTP走私: CL.TE/TE.CL/CL.0/H2.TE (James Kettle方法论) |
| `waf-bypasser.md` | WAF识别绕过: Cloudflare/AWS/ModSecurity/FortiWeb/Imperva |
| `confusion-attacker.md` | 语义混淆: Path Traversal/SSRF/Host Header (Orange Tsai方法论) |
| `race-condition.md` | 竞态条件: TOCTOU/单包攻击/Turbo Intruder/并发支付 |
| `supply-chain-hunter.md` | 供应链攻击: npm/PyPI/CI-CD/依赖投毒 |
| `binary-exploiter.md` | 反序列化RCE: node-serialize/pickle/yaml; ROP/堆利用 (LiveOverflow方法论) |
| `cloud-escape.md` | 容器逃逸: Docker/K8s/AWS IAM/云凭据窃取 |
| `mobile-reverser.md` | 移动逆向: Android/iOS/Frida/SSL Pinning绕过/APK脱壳 |
| `web3-auditor.md` | 智能合约审计: Solidity/DeFi/闪电贷/重入攻击 |
| `llm-redteamer.md` | LLM攻击: Prompt Injection/RAG投毒/Agent安全 |
| `ad-pwn.md` | AD域渗透: Kerberos/DCSync/ADCS/BloodHound |
| `bug-bounty-methodologist.md` | 赏金方法论: 侦察/子域/Passive Recon/NahamSec+Jason Haddix整合 |
| `report-humanizer.md` | 报告去AI味: 按H1过审模板输出 |

### 🔧 weapons/ — 自动化探测武器 (6件)

| 文件 | 用途 |
|------|------|
| `universal-probe.py` | **万能探针** — SQLi/IDOR/Cart/Edit/FileUpload全支持。POST/GET/Cookie/Form/multipart全覆盖。Agent打CTF的主武器 |
| `smuggler-probe.py` | HTTP走私探针 — CL.TE/TE.CL/CL.0 一键自动探测 |
| `api-probe.py` | API扫描 — 未授权端点/JWT弱密钥/Mass Assignment/IDOR快速扫描 |
| `inject-probe.py` | 注入探针 — SQLi+XSS 8种payload自动判别 |
| `deser-probe.py` | 反序列化探针 — node-serialize/pickle/yaml RCE探测 |
| `dep-audit.py` | 依赖审计 — npm audit + CVE快速检查 |

### ⚙️ config/ — 配置中心 (2件)

| 文件 | 行 | 用途 |
|------|---|------|
| `swarm-presets.json` | 348 | **组合技预设库** — 18套场景预设+5条H1漏洞链。可随时增删改Agent名单/触发词/分数。hive-dispatcher实时读取 |
| `agent-skill-matrix.json` | 136 | **Agent-Skill映射矩阵** — 每个Agent配什么技能、触发词、知识库路径。废弃项留档 |

### 📊 可视化面板

| 文件 | 用途 |
|------|------|
| `dashboard.html` | **实时战况网页** — 打开即看: Agent谁在干活/最近发现/系统指标/PI状态/Bash连用次数。数据嵌入HTML无需服务器 |

### ⌨️ 快捷键

| 文件 | 用途 |
|------|------|
| `h` | **一字全流程** — brain分析→选Agent→hive-mind初始化→探针跑→live面板 |
| `p` | **一键派PI** — p s=scout, p d=dev, p a=audit, p r=recon... fire-and-forget |
| `p.sh` | p命令的Windows兼容版 |

---

## 18套组合技速查

| 触发词 | Agent数 | 组合 |
|--------|--------|------|
| 火力全开/全上/倾巢 | 16 | 全部Agent |
| 蜘蛛/全自动/爬全站 | 10 | bb-methodologist+api+sqli+xss+smuggler+waf+confusion+race+supply+binary |
| 全面/完整审计 | 6 | api+sqli+xss+smuggler+waf+confusion |
| SRC挖洞/HackerOne | 5 | bb-methodologist+api+sqli+xss+confusion |
| 快扫/扫一下 | 4 | api+sqli+xss+waf |
| 注入扫描 | 4 | sqli+xss+confusion+smuggler |
| API安全/GraphQL | 3 | api+confusion+race |
| 云安全/容器 | 3 | cloud-escape+api+supply |
| 智能合约/Web3 | 3 | web3+api+race |
| LLM攻击/AI安全 | 3 | llm+api+xss |
| AD域/Kerberos | 3 | ad-pwn+confusion+supply |
| 二进制/ROP/Ghidra | 3 | binary+confusion+supply |
| 移动/Android/iOS | 3 | mobile+api+confusion |
| 供应链/npm/PyPI | 3 | supply+api+confusion |
| + 5条HackerOne真实漏洞链 | 2-3 | XSS→CSRF→ATO / SSRF→云密钥窃取 等 |

## 现场组队（不用预设）

```bash
python hive-mind.py swarm --agents "sql-injector,xss-hunter,waf" --target "https://x.com"
# 16安全Agent + 9 PI Agent 任意排列组合
```

## 核心流水线

```
你说一句话 → hive-brain分析攻击面 → 自动选Agent组合
  → hive-dispatcher派蜂群 (平行/环形/星型拓扑)
  → universal-probe 自动SQLi/IDOR/Cart/FileUpload
  → 发现写hive-mind (三层记忆+Git追踪)
  → hive-live 出战报面板
  → 全程overseer监督 (跳过brain=exit(2), 多Bash=强派PI)
```

## 借鉴项目

| 项目 | 借鉴了什么 |
|------|-----------|
| Claude Flow (Ruflo) | 蜂群拓扑/共识投票/Token预算/学习闭环 |
| Letta (MemGPT) | 三层记忆(Core/Recall/Archival)/Git追踪/战后复盘 |
| ByteDance deer-flow | 沙箱隔离/Docker执行 |
| AgentPrism | 可视化面板颜色编码(绿=活跃/白=完成/黄=卡住) |
| Dify | 节点染色+进度条 |
| thefuck (nvbn) | 命令纠错自动修复 (hive-repair) |

## 许可

MIT License — 随便用

## 作者

三玖的蜂巢黑客团队 | GitHub: [tlyyxjz/HiveSwarm](https://github.com/tlyyxjz/HiveSwarm)
