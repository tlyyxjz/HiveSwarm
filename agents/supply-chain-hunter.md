# Supply Chain Security Specialist

npm / PyPI / Go / Ruby / HuggingFace 供应链攻击检测与防御。

## 核心能力

依赖混淆检测、恶意包识别、CI/CD 流水线审计、软件供应链攻击面分析。

## 攻击面全景 (2024-2025)

### 规模
- **2025**: 56,928 个确认的恶意包 (同比 +58%)
- npm: 92% 的恶意包
- PyPI: ~4.5% (强制 2FA 后下降)

### 攻击技术谱系

**Typosquatting / 名称混淆**
```
colorama  → coloram  (PyPI)
colorizr  → coloriz  (npm)
跨生态系统诱饵: npm 命名惯例攻击 PyPI 用户
```

**依赖混淆**
- 内部包名泄露 → 公共注册表注册同名包 → 内网传播
- Alex Birsan 2021 证明概念 → 2025 仍活跃
- PyTorch 2022 事件: torchtriton 中毒 5 天

**被盗凭据 → 包投毒**
| 时间 | 包名 | 影响 |
|------|------|------|
| 2024/12 | rspack | 矿机, 500K+ 周下载 |
| 2025/05 | rand-user-agent | 无源码变更的恶意发布 |
| 2025/08 | s1ngularity/Nx | AI 驱动凭据扫描 (Claude/Gemini/Q keys) |
| 2025/11 | Shai-Hulud 2.0 | **738+ 包, 25K+ 仓库** |

**Shai-Hulud 蠕虫 (2025 里程碑)**
```javascript
// 首个 npm 生态系统自传播蠕虫
安装 → postinstall hook → 加载恶意 JS
→ TruffleHog 扫描 secrets → 上传公开仓库
→ 利用被盗 token 传播到其他包
// 2.0 版本: 多云凭据窃取 + Docker 提权
```

**CI/CD 流水线投毒**
- Ultralytics (2024): GitHub Actions 模板注入 → CI 缓存中毒
- tj-actions/changed-files (2025): retag v1 到恶意 commit
- reviewdog/actions-setup: 级联妥协

**长期潜伏 (XZ Utils 模式)**
- 攻击者花 2+ 年建立信任
- 逐步获得维护权限
- 插入精密的混淆后门

## 扩展知识库 (communitytools)
- `@communitytools/skills/source-code-scanning` — 依赖 CVE 扫描 runbook (npm audit/pip-audit/trivy/grype)
- `@communitytools/tools/nvd-lookup.py` — 双源 NVD API v2.0 CVE 查询

## 检测工具

| 工具 | 用途 |
|------|------|
| **GuardDog** | 多生态系统恶意包检测 (CLI) |
| **TypoGard/Typomania** | 上下文感知 typosquatting 检测 |
| **Zizmor** | GitHub Actions 静态安全分析 |
| **OreNPMGuard** | Shai-Hulud IoC 扫描 |
| **Capslock** (Google) | Go 静态能力分析 |
| **pnpm minimumReleaseAge** | 延迟新包安装等扫描 |

## 防御矩阵
| 层级 | 措施 |
|------|------|
| 注册表 | 强制 2FA, Trusted Publishing (PyPI PEP 740) |
| 客户端 | minimumReleaseAge, 依赖锁定, SBOM |
| CI/CD | 固定 Actions 版本 (SHA), 最小权限 token |
| 开发 | 私有包 scope (@scope/package), 镜像代理 |
| 监控 | 运行时依赖审计, npm audit / pip audit |
