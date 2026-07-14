# 三玖Dashboard 架构分层：逻辑/数据层 ⇄ 视图/交互层

> 目的：给前端负责人一份权威"接口契约"。把逻辑/数据层(model)挖出来、列清楚，并把它与视图/交互层(Tk UI)之间的**所有钩子**列全。
> 现状：逻辑层大部分**已经是独立模块**；唯一跨两层的是 `AppController`(编排/上帝对象)。物理拆分见 §7。

## 1. 分层总览

```text
视图/交互层 (Tkinter UI)          ← 前端负责人的主战场
  pet_window / bubble_window / dashboard_ui / pet_menu / settings_window / tray_manager / widgets
        ↑ 钩子(回调/方法/纯函数/配置/事件)
编排层 AppController              ← 混了两层(god object)，建议后期拆出 AppCore
        ↓
逻辑/数据层 (无 Tk，可单测)       ← 已基本独立
  config / data_loader / pet_state / pet_brain / notification_queue / diary_manager
  / event_bus / after_manager / notifications(MilestoneTracker) / themes / webhook_server / startup
```

## 2. 逻辑/数据层模块（Tk 无关，已单测）

| 模块 | 职责 | 关键导出 |
|------|------|----------|
| `config.py` | 配置读写/默认/校验 | `ConfigManager`, `DEFAULTS` |
| `data_loader.py` | 数据源抽象 + 校验 | `DataSource`, `LocalJsonSource`, `HttpJsonSource`, `create_data_source`, `validate_projects`, `DataError` |
| `pet_state.py` | 桌宠状态机 | `PetState`, `PetEvent`, `PetStateMachine`, `TRANSITIONS`, `WAKE_EVENTS` |
| `pet_brain.py` | "说什么"的大脑 | `PetBrain`, `LocalTemplateBrain`, `CozeBrain`, `BrainRouter`, `build_brain`, `load_secrets`, `PetContext`, `TRIGGER_*`, `TEMPLATES`, `TRIGGER_PROMPTS` |
| `notification_queue.py` | 通知/气泡排队 | `NotificationQueue` |
| `diary_manager.py` | 事件→碎碎念文案 | `DiaryManager` |
| `event_bus.py` | 解耦事件 | `EventBus`, `AppEvent`, `EventType` |
| `after_manager.py` | Tk after 生命周期 | `AfterManager`（薄封装，逻辑侧） |
| `notifications.py` | **混合**：`MilestoneTracker`(逻辑) + `ToastNotification`(视图) | 见下 §4 注 |
| `themes.py` | 主题数据 | `get_theme`, `THEMES` |
| `webhook_server.py` | 唯一真·服务端(可选本地) | `WebhookServer`, `parse_webhook_payload` |
| `startup.py` | 开机自启注册表 | `set_startup`, `is_startup_enabled` |

## 3. 视图/交互层模块（Tkinter）

| 模块 | 职责 | 备注 |
|------|------|------|
| `pet_window.py` | 桌宠窗口/拖动/点击/渲染 | 内含纯函数 `is_head_region`/`calculate_edge_snap`/`resolve_pet_asset_path`(逻辑住在视图文件里，可上移) |
| `bubble_window.py` | 对话气泡窗口 | 含纯函数 `calculate_bubble_position` |
| `dashboard_ui.py` | 项目面板(Canvas) | 含纯函数 `calculate_dashboard_follow_position` |
| `pet_menu.py` | 右键菜单 | |
| `settings_window.py` | 设置面板(CustomTkinter) | |
| `tray_manager.py` | 系统托盘 | |
| `widgets.py` | 卡片/进度条组件 | |

## 4. 编排层 `AppController`（god object，混两层）

它**持有逻辑对象**(cfg/data_source/brain/milestone/diary/event_bus)，又**创建视图对象**(dash/pet/pet_bubble/pet_menu/settings_win/tray)，并把两边用钩子连起来。后期建议拆成 `AppCore`(逻辑) + 视图接线壳(§7)。

> 注：`notifications.py` 一个文件里混了 `MilestoneTracker`(逻辑) 和 `ToastNotification`(视图)，建议日后拆成两个文件。

## 5. 钩子清单（视图 ⇄ 逻辑 的接口契约）★前端照这个接★

### 5.1 视图 → 逻辑（用户操作打进来，都是 AppController 的方法）

```text
handle_pet_click()                 单击桌宠（非头部）→ 随机说一句
handle_head_touch()                点到头部区域 → 摸头反应（前端用 is_head_region 判定后调）
handle_pet_double_click()          双击 → 开/关项目面板（受 double_click_toggles_dashboard）
handle_pet_move(pos)               拖动中 → 重定位气泡/面板（拖动结束的吸附见 §6）
show_pet_menu()                    右键 → 切换右键菜单
handle_pet_menu_action(label)      菜单项点击
handle_task_toggle(pid, task)      面板里勾选任务 → 写回数据并重算进度
toggle_dashboard()                 显隐项目面板
refresh_now()                      手动刷新数据
apply_settings(changes)            设置变更 → 运行时生效（dict: {键:新值}）
show_settings()/show_pet_settings()/show_appearance_settings()   打开设置对应页
shutdown()                         统一退出
```

### 5.2 逻辑 → 视图（逻辑产生的效果，打到视图对象上）

```text
show_pet_bubble(msg)               → 气泡显示一句（内部走 NotificationQueue → BubbleWindow）
pet.set_state(PetState.X)          → 切换立绘/状态（SPEAKING/SLEEPING/...）
pet.hide()/show()/set_size()/set_opacity()/set_font_size()/update_theme()
dash.set_projects(projects)        → 刷新项目卡片
dash.reposition_near(anchor_rect)  → 面板跟随桌宠
notifications.push(title, msg)     → Toast
pet_bubble.set_enabled/ set_default_duration / set_opacity
settings_win.open(tab) / sync_values(values)
tray.start()/stop()
```

### 5.3 纯函数（视图直接调用，无副作用，已单测）

```text
pet_window.is_head_region(y, size, ratio=0.35) -> bool          点击是否在头部
pet_window.calculate_edge_snap(x, y, size, screen, threshold) -> (x, y)   靠边吸附位置
pet_window.resolve_pet_asset_path(asset_dir, state) -> Path|None  选立绘(缺失回退 idle)
bubble_window.calculate_bubble_position(anchor, bubble_size, screen) -> (x, y)  气泡位置(翻边+夹屏)
dashboard_ui.calculate_dashboard_follow_position(anchor, dash_size, screen) -> (x, y)  面板位置
```

### 5.4 配置键契约（改这些就改行为，存 dashboard_config.json）

```text
窗口：opacity, always_on_top, theme, font_size, card_style, position_x/y, refresh_seconds
桌宠：pet_enabled, pet_size, pet_character, pet_bubble_enabled, pet_bubble_duration_ms,
      double_click_toggles_dashboard, head_touch_enabled, edge_snap_enabled,
      idle_talk_enabled, idle_talk_interval_minutes, sleep_enabled, sleep_after_minutes
通知：notifications_enabled, notify_milestone/status/completion/source_error,
      daily_chatter_enabled, toast/bubble/sound_notifications_enabled
数据源：data_source{type, path|url, timeout_seconds}
服务/AI：webhook{enabled,host,port}, brain{coze{enabled,base,bot_id,user_id,timeouts}}
密钥(不进配置/ git)：~/.miku-dashboard/secrets.json → COZE_API_TOKEN 等
```

### 5.5 事件（EventBus，逻辑内部解耦；视图一般不用直接碰）

```text
EventType: PROJECT_PROGRESS_CHANGED / PROJECT_MILESTONE_REACHED / PROJECT_COMPLETED /
TASK_COMPLETED / TASK_UNDONE / DATA_REFRESH_SUCCESS / DATA_REFRESH_FAILED / THEME_CHANGED /
USER_CLICK_PET / USER_DOUBLE_CLICK_PET / USER_DRAG_PET / TIME_GREETING / IDLE_TOO_LONG /
APP_START / APP_EXIT
```

## 6. 还没接上的钩子（逻辑已就绪，等前端在视图里接线）

```text
[摸头] ✅ 已接(2026-06-23)。PetWindow.__init__ 增 on_head_touch 回调；_on_click 里
       is_head_region(evt.y, size) 为真就调 on_head_touch()，否则照常 on_click()。
       AppController 传 on_head_touch=self.handle_head_touch。开关 head_touch_enabled 在
       handle_head_touch 内部判定。回归测试见 test_pet_mvp.PetWindowHookTests。
[贴边吸附] ✅ 已接(2026-06-23)。PetWindow.__init__ 增 edge_snap_enabled 回调(provider)；
       _on_drag_end 里若发生过移动就调 _maybe_snap_to_edge()，开关开时用 calculate_edge_snap
       算位置再 geometry(...) 并回调 on_move。纯函数不碰窗口，避开老的"可移动范围变小"坑。
       AppController 传 edge_snap_enabled=lambda: cfg.get("edge_snap_enabled", True)。
[角色选择] 逻辑就绪(pet_character 配置键)。前端要做：设置页加角色下拉 + 备用素材目录。
[睡眠立绘] 现用"睡了Zzz"角标占位。前端要做：补 miku_sleeping.png 或睡眠时整体变暗。
[设置页输 key] 前端要做：设置页加 Coze bot_id/token 输入，写入 config.brain.coze 和 secrets.json。
[DeepSeek 聊天窗] 属后续：独立聊天窗(多轮) + DeepSeek 推理路径。
```

## 7. 物理拆分建议（god-object 拆 AppController，后期维护）

把 `AppController` 的**逻辑**抽到一个 Tk 无关的 `AppCore`：持有 cfg/data_source/brain/milestone，
暴露"决策型"方法(刷新→返回数据+变化、由项目算状态事件、算下次碎碎念延时、任务写回…)，
对视图效果走**钩子接口**(on_speak/on_pet_state/on_projects/on_toast…)。
`AppController` 退化为视图接线壳：建窗口、连回调、把钩子指到视图方法。

代价提示：会改动中心文件 + 约一半的 195 个测试，建议**分阶段、每步保持测试绿**，别一把梭。
