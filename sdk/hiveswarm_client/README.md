# HiveSwarm Python SDK

> Async + Sync HTTP client for [HiveSwarm](https://github.com/) gateway

## 安装

```bash
# 暂未发布到 PyPI, 直接从源码
pip install -e sdk/
# 依赖: httpx>=0.24
```

## 快速开始

### Async（推荐）

```python
import asyncio
from hiveswarm_client import HiveSwarmClient

async def main():
    async with HiveSwarmClient(base_url="http://localhost:8000") as client:
        # 健康检查
        health = await client.health()
        print(f"Status: {health.status}")

        # 列出所有 skill
        skills = await client.list_skills()
        for s in skills.skills:
            print(f"  - {s.name}")

        # 提交任务
        result = await client.submit_task("帮我做一个 PPT", target=None)
        print(f"Task {result.task_id}: {result.status}")

asyncio.run(main())
```

### Sync（一行调用）

```python
from hiveswarm_client import SyncHiveSwarmClient

client = SyncHiveSwarmClient(base_url="http://localhost:8000")
health = client.health()  # 同步阻塞调用
print(health.status)
```

## API

### `submit_task(request, *, target=None, async_mode=False)`

提交任务到 Brain 拆解 → Work 执行。

| 参数 | 类型 | 说明 |
|------|------|------|
| `request` | `str` | 自然语言任务描述（必填） |
| `target` | `str \| None` | 扫描类任务的目标路径（如 "." 或 URL） |
| `async_mode` | `bool` | True → 立即返回 `task_id`；False → 阻塞等结果 |

**Returns**：
- `TaskResponse` (同步模式) — 包含完整结果
- `TaskAcceptedResponse` (异步模式) — 只含 `task_id` 和 `status: "accepted"`

### `get_task(task_id)`

获取已提交任务的结果。配合 `async_mode=True` 使用。

### `list_skills()`

列出所有注册的 skill + 健康度。

### `stream_events()`

**异步生成器**：订阅 Server-Sent Events 流，实时接收系统事件。

```python
async with client.stream_events() as events:
    async for event in events:
        print(event)  # dict: {"type": "task.started", "ts": "...", ...}
```

### `health()`

健康检查端点。返回 `{status: "ok"}` 或降级状态。

## 错误处理

所有非 2xx 响应会抛 `httpx.HTTPStatusError`：

```python
from httpx import HTTPStatusError

try:
    result = await client.get_task("non-existent")
except HTTPStatusError as e:
    if e.response.status_code == 404:
        print("Task not found")
```

网络超时通过 `timeout` 参数控制（默认 120s）。

## 鉴权

未来支持（gateway 鉴权 endpoint 已预留）：`HiveSwarmClient(base_url, token="...")`。

## License

Apache 2.0