# 测试与本地测试集规划

> 目标：为全系统建立分层测试体系，并提供一套可复用的**本地测试集**，
> 覆盖 `kaleido-vault` 与 `kaleido-profile`（含二者对接），并为后续模块预留扩展位。

## 一、测试分层

| 层 | 目录 | 目标 | 联网 |
|---|---|---|---|
| 单元 | `tests/<module>/` | 单模块逻辑正确性 | 否 |
| 对接 | `tests/integration/` | 跨模块协作（如 profile↔vault） | 否 |
| 端到端 | `tests/e2e/` | API 全链路（LLM 用桩/录制） | 否 |
| 联调（可选，默认跳过） | `tests/live/` | 真实 DeepSeek 调用 | 是 |

原则：

- 所有测试用 `tmp_path` 作为存储根，**绝不写真实 `data/`**。
- 需要云模型的测试一律桩化（`llm_client` 可注入），CI 不联网。
- 测试与本地测试集共用同一套 fixtures，避免「测试数据」与「联调数据」两套口径。

## 二、本地测试集（fixtures）

### 2.1 目录结构（已实现）

```
tests/fixtures/
├── __init__.py                  # 加载工具：load_student_samples()
└── students/
    └── samples.json             # valid(12：4 类型×3 程度) + edge(边界/非法)
```

> 预留（后续模块）：`expected/frameworks/`（金标准快照）、`resources/`（forge/match 样例资源）。

### 2.2 学生样例 schema

```json
{
  "name": "小明",
  "attributes": {
    "disability": "visual",
    "severity": "moderate",
    "cognitive_level": "primary_low",
    "sensory_preference": null,
    "rehab_goals": ["language", "cognitive"],
    "learning_pace": "slow"
  }
}
```

### 2.3 覆盖矩阵（参数化）

| 类型 \ 程度 | mild | moderate | severe |
|---|---|---|---|
| visual | ✓ | ✓ | ✓ |
| hearing | ✓ | ✓ | ✓ |
| intellectual | ✓ | ✓ | ✓ |
| autism | ✓ | ✓ | ✓ |

**边界样例**（`edge_cases.json`）：

- 缺省 `sensory_preference`：应由类型默认值推导。
- 显式覆盖感官偏好：应尊重显式值。
- 非法枚举（disability / severity / rehab_goals）：应抛 `ValidationError`。
- `severe` 压缩：指标仅保留核心、评分标准压到 3 级、观测频率升为 `per_lesson`。
- 认知等级过滤：低于 `min_cognitive_level` 的指标应被剔除（如 preschool 无盲文指标）。
- 多重障碍：带 `parent` 组合的类型表达（后续扩展）。

### 2.4 金标准（golden）生成与维护

- 初次由脚本 `scripts/gen_fixtures.py` 生成；或 pytest 快照插件 `--snapshot-update`。
- 金标准经特教教师抽样确认后**冻结**；任何框架逻辑改动必须**显式更新并评审**。
- 断言方式：生成结果与金标准做结构化比对（忽略时间戳等易变字段）。

## 三、`kaleido-vault` 测试（`tests/vault/`）

> 状态：已实现，全部通过。

| 文件 | 覆盖点 |
|---|---|
| `test_jsonstore.py` | 原子写（临时文件 + replace）、文件锁、读不存在抛错、损坏文件隔离 |
| `test_collection.py` | 增删改查、`next_id` 自增与零填充、分页边界、幂等键、点路径索引筛选 |
| `test_vault.py` | 集合注册、配置驱动的索引字段/前缀、`namespaces()` |
| `test_concurrency.py` | 多线程 / 多进程并发写不丢数据、计数器无冲突 |
| `test_recovery.py` | 删除 `index.json` 后 `reindex()` 重建、残留 `.tmp` 清理、分片与索引一致性 |
| `test_api.py` | 通用 REST 增删改查、错误码 |

## 四、profile ↔ vault 对接测试（`tests/integration/test_profile_vault.py`）

> 状态：已实现，全部通过。

1. **建档案落盘**：`ProfileService.create_student` → 断言 `data/students/p_0001.json` 存在、结构正确；`index.json` 含 entry 与 idempotency。
2. **重启读取**：丢弃 `ProfileService` 与 `Vault` 实例，重新构造后 `get_student` 能读回同一档案。
3. **幂等**：相同 `client_request_id` 二次建档抛 `ConflictError`，且只落一个分片。
4. **更新**：改属性 → 分片更新、`updated_at` 变化、评价框架重建。
5. **删除**：分片删除、索引 entry 移除。
6. **列表筛选**：按 `disability` / `cognitive_level` 过滤；分页边界。
7. **一致性**：遍历索引 `entries`，逐个分片可读且 id 匹配；`reindex()` 幂等。
8. **共存**：vault 通用 API 与 profile 领域 API 读写同一集合互不干扰。

> 成功标准：`tests/profile/*` 在 vault 改造后**不改动**即全绿，即视为对接成功。

## 五、`kaleido-forge` 测试（`tests/forge/`）

> 状态：已实现，全部通过（`StubClient` 离线）。

| 文件 | 覆盖点 |
|---|---|
| `test_llm_client.py` | 桩调用、配置工厂、缺密钥、请求构造、重试与错误映射 |
| `test_prompts.py` | 四类模板渲染、约束注入、缺失占位、缺失模板 |
| `test_service.py` | 画像/属性两种来源、Prompt 拼装、落库、筛选 |
| `test_api.py` | 生成、详情、列表、非法请求、资源类型 |

## 六、端到端（`tests/e2e/`，后续）

- 建档 → 生成（桩 `llm_client`）→ 质检 → 落库 → 匹配 全链路。
- 用本地测试集灌入，产出可复现的样例资源。

## 七、运行方式

```powershell
pytest -q                                   # 全部（跳过 live）
pytest -q tests/vault tests/integration     # 仅 vault 与对接
pytest -q tests/forge                       # 仅 forge
pytest -q tests/live                        # 真实联调（需 API Key，默认跳过）
```

pytest 配置（`pyproject.toml`）：`pythonpath=src`；`tests/live` 通过 `-m live` 选择性运行。

## 八、质量门（本地 / CI）

- `ruff check` 通过。
- `pyright` 0 error。
- `pytest` 全绿。
