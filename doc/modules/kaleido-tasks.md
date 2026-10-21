# kaleido-tasks 模块开发规划

> 版本 v1.0 ｜ 定位：异步任务层
> 上游：`kaleido-forge` / `kaleido-facet` 等耗时业务
> 下游：`kaleido-vault`（任务状态落库）

## 一、模块概述

`kaleido-tasks` 把**生成、质检、迭代等耗时任务**从请求线程中剥离，交由后台
工作线程异步执行，并把任务状态持久化到 `kaleido-vault` 的 `tasks` 集合。
配合云端模型**峰谷定价**，支持把批量任务调度到**闲时**（夜间/周末/节假日）
执行，从而将生成成本减半。

### 1.1 职责边界

| 做 | 不做 |
|---|---|
| 任务排队、优先级调度、并发执行 | 具体业务生成（归 forge） |
| 任务状态持久化、查询、取消、重试 | 质量评分（归 facet） |
| 闲时调度（成本优化） | 模型密钥与合规（归 guard） |

设计原则：**内存队列 + 后台线程 + 状态落盘**，轻量、无外部中间件依赖。

## 二、架构与数据流

```
CreateTaskRequest
   │  task_type / payload / priority / defer_off_peak
   ▼
TaskService.submit ──► vault.tasks（status=pending）
   │
   ▼
TaskQueue（优先级最小堆）
   │
   ▼  后台工作线程
is_off_peak? ── 否 ──► 重新入队，稍后再试
   │ 是
   ▼
handler(payload)（如 forge.generate）
   │
   ├─ 成功 ──► status=succeeded + result
   └─ 失败 ──► 未达上限则重试，否则 status=failed + error
```

## 三、目录结构

```
src/kaleido/tasks/
├── __init__.py      对外导出 TaskService / TaskModel / CreateTaskRequest
├── models.py        CreateTaskRequest / TaskModel
├── queue.py         TaskQueue（优先级队列，条件变量阻塞）
├── schedule.py      is_off_peak：时段/周末/节假日判定
├── service.py       TaskService：注册处理器、提交、执行、取消、重试
└── api.py           Bottle 路由
configs/tasks/tasks.yaml
tests/tasks/
```

## 四、配置

`configs/tasks/tasks.yaml`：

```yaml
worker_count: 2                     # 后台工作线程数
max_recoveries: 3                   # 进程重启后中断任务的最大自动恢复次数
progress_max_chars: 4000            # 任务面板保留的思考/正文增量字符数
progress_interval_seconds: 0.5      # 流式进度写盘间隔
schedule:
  defer_poll_seconds: 5             # 闲时任务未到窗口时的轮询间隔
  off_peak:
    weekends: true                  # 周末整天算闲时
    holidays: []                    # 法定节假日 YYYY-MM-DD
    windows:
      - start: "22:00"              # 每日闲时时段，支持跨零点
        end: "07:00"
```

## 五、任务状态机

```
pending ──(工作线程取用)──► running ──┬─► succeeded
   ▲                                  ├─► failed（超过 max_attempts）
   └────────(失败重试)────────────────┘
任意非终态 ──(cancel)──► cancelled
```

- 状态：`pending / running / succeeded / failed / cancelled`。
- `attempts` 记录已尝试次数，`max_attempts` 控制重试上限。
- 取消为协作式：执行中的任务在完成后若已被取消，则保留取消态、丢弃结果。

### 5.1 进程重启恢复

统一服务在注册完全部处理器后调用 `TaskService.recover()`：

- `pending` 任务重新入队，继续执行；
- `running` 任务视为上次进程中断，回退该次尝试并重新入队；
- 每个任务用 `recoveries` 记录恢复次数，超过 `max_recoveries` 才标记失败，
  避免“启动即崩溃”造成无限重启；
- 处理器尚未注册的任务保持原状，待注册后再恢复。

### 5.2 流式进度

大模型调用统一走流式，任务文档额外保存 `reasoning`（思考）与
`stream_content`（正文增量）：

- 处理器声明为 `(payload, progress)` 两个参数时，服务会注入进度回调；
- 增量按 `progress_interval_seconds` 节流写盘，只保留最近
  `progress_max_chars` 字符，避免任务 JSON 无限膨胀；
- HTTP 流式接口通过 `record_stream` 同步写入进度；
- 任务面板轮询任务列表即可实时展示思考内容。

## 六、闲时调度

`is_off_peak(now, schedule)` 判定规则（满足其一即为闲时）：

1. 日期命中 `holidays`；
2. `weekends=true` 且为周六/周日；
3. 时刻落在任一 `windows` 区间内（`start > end` 表示跨零点）。

`defer_off_peak=true` 的任务在工作线程取出时若处于高峰，会被重新入队，
等待下一轮轮询或进入闲时后再执行。

## 七、接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/tasks` | 提交任务 |
| GET | `/api/v1/tasks` | 分页/筛选（`task_type / status`） |
| GET | `/api/v1/tasks/types` | 已注册任务类型 |
| GET | `/api/v1/tasks/<id>` | 任务详情 |
| DELETE | `/api/v1/tasks/<id>` | 取消任务 |

请求示例：

```json
{
  "task_type": "forge.generate",
  "payload": {
    "profile_id": "p_0001",
    "resource_type": "courseware",
    "topic": "认识四季"
  },
  "priority": 0,
  "max_attempts": 2,
  "defer_off_peak": true
}
```

## 八、与其它模块的对接

- **forge**：统一服务入口注册 `forge.generate` → `ForgeService.generate`，
  实现「异步批量生成」。
- **vault**：任务落 `tasks` 集合（`envelope=true`，索引字段 `task_type / status`）。

## 九、测试

| 文件 | 覆盖点 |
|---|---|
| `test_schedule.py` | 时段、跨零点、周末、节假日、无配置 |
| `test_service.py` | 执行、未注册类型、失败重试、取消、闲时调度、列表过滤 |
| `test_api.py` | 提交、查询、列表、类型、非法类型 400 |

全部离线；闲时逻辑通过注入时钟（`clock`）确定化，不依赖真实时间。

## 十、完成定义（DoD）

- 队列、调度、服务、API、配置全部实现。
- 任务状态可持久化并按类型/状态检索；支持取消与重试。
- 闲时任务仅在闲时执行。
- `pytest` 全绿，`pyright` 0 error。

## 十一、实现状态（已落地）

- **代码**：`src/kaleido/tasks/{models,queue,schedule,service,api}.py`。
- **配置**：`configs/tasks/tasks.yaml`；vault 新增 `tasks` 索引字段。
- **测试**：`tests/tasks/`。
- **对接**：统一入口 `src/kaleido/api/app.py` 注册 `forge.generate`。
