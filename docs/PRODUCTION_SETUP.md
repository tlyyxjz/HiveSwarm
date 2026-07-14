# HiveSwarm 生产部署指南

> 基于 `config/production.toml.example` 的完整部署步骤

## 📋 前置清单

### 必装依赖

```bash
pip install -e .
# 或者：pip install -r requirements.txt
# 含：httpx, pydantic, fastapi, uvicorn, gradio, reportlab, python-pptx
```

### 必填环境变量

复制 `config/production.toml.example` 为 `production.toml`，然后**设置这些环境变量**：

| 变量 | 用途 | 来源 |
|------|------|------|
| `MINIMAX_API_KEY` | 默认 LLM | 蜂巢后台申请 |
| `DEEPSEEK_API_KEY` | 备选 LLM | api.deepseek.com |
| `ANTHROPIC_API_KEY` | Claude | console.anthropic.com |
| `OPENAI_API_KEY` | GPT | platform.openai.com |
| `DASHSCOPE_API_KEY` | 通义千问 (可选) | 阿里云 |
| `ZHIPU_API_KEY` | 智谱 GLM (可选) | open.bigmodel.cn |
| `MOONSHOT_API_KEY` | Moonshot Kimi (可选) | api.moonshot.cn |
| `STRIPE_API_KEY` | 计费 (可选) | dashboard.stripe.com |

```bash
# Linux/macOS
export MINIMAX_API_KEY=...
export DEEPSEEK_API_KEY=...
# ...

# Windows PowerShell
$env:MINIMAX_API_KEY = "..."
$env:DEEPSEEK_API_KEY = "..."
```

---

## 🚀 启动步骤

### 1. 准备运行时目录

```bash
mkdir -p ~/.hiveswarm/{reports,exports,logs,memory}
```

### 2. 验证配置

```bash
python -c "
import sys
sys.path.insert(0, '.')
from stub.config_loader import load_config
cfg = load_config('config/production.toml')
print('OK:', cfg.brain.active_provider)
print('Skills:', cfg.skills.enabled)
"
```

### 3. 启动 Gateway（HTTP API）

```bash
python -m gateway --config config/production.toml
# 监听 0.0.0.0:8000
```

### 4. 启动 Dashboard（可选）

```bash
python -c "
from stub.dashboard_gradio import GradioDashboard
GradioDashboard(port=7860).launch(share=False)
"
# 浏览器开 http://localhost:7860
```

### 5. 启动 Docker（推荐）

```bash
docker-compose up -d
# 含 gateway + dashboard + postgres (可选)
```

---

## 🔍 配置项速查

| Section | 关键字段 | 生产建议 |
|---------|---------|---------|
| `[brain]` | `active_provider` | 改用公司采购的模型 |
| `[brain]` | `planner_system_prompt` | 调成公司业务语气 |
| `[memory]` | `ttl_days` | 90 天（合规要求） |
| `[repair]` | `strategy` | `switch_first` 或 `reassemble_first` |
| `[monitor]` | `dashboard_port` | 反向代理到 443 |
| `[gateway]` | `workers` | CPU 核数 × 2 |
| `[local]` | `enabled` | **必须 false**（公司禁用 Ollama）|

---

## ⚠️ 安全检查清单

- [ ] 所有 `api_key` 都用环境变量（**不** 硬编码）
- [ ] `production.toml` 加入 `.gitignore`
- [ ] HTTPS 反代前置（Nginx/Caddy）
- [ ] Gateway 加 rate limit
- [ ] Dashboard 加 Basic Auth（如果暴露公网）
- [ ] `[local] enabled = false`（确认 Ollama 不加载）
- [ ] 日志轮转配置（logrotate / Docker log driver）

---

## 🐛 常见问题

### "MINIMAX_API_KEY not set"
```bash
# PowerShell 检查
Get-ChildItem env:MINIMAX_API_KEY
# 必须有值, 不为空
```

### "Skill ppt_pack import failed"
```bash
# 检查 skills/ppt_pack/src 是否在 sys.path
# 或用 pip install -e skills/ppt_pack/
pip install -e skills/ppt_pack/
pip install -e skills/agentvet_pack/
pip install -e skills/crawler_pack/
pip install -e skills/web_search_pack/
```

### "Ollama 还在加载"
检查 `production.toml` 里 `[local] enabled = false`。

### Dashboard 起不来
看 `~/.hiveswarm/logs/events.jsonl` 错误。常见原因：
- 端口被占（dashboard_port）
- proxy 拦截（同 NO_PROXY 问题）→ 设 `os.environ['NO_PROXY']='*'`

---

## 📞 监控接入

推荐接入：
- **Prometheus**：gateway 暴露 `/metrics`
- **Loki**：events.jsonl 直接传
- **Sentry**：捕获异常（需装 `sentry-sdk`）

---

**最后更新**: 2026-06-29
**对应版本**: v0.2.0