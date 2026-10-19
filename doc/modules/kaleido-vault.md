# kaleido-vault 模块开发规划

> 版本 v1.0 ｜ 定位：本地 JSON 文档库（数据层 / 支撑模块）
> 上游：各业务模块（profile / forge / facet / match / loop / tasks）
> 下游：本地文件系统（`data/`）

## 一、模块概述

`kaleido-vault` 是全系统**统一的持久化底座**：把各业务模块产出的文档以本地 JSON 形式**分片存储**、**加锁写入**、**建立内存索引**并提供检索。

`kaleido-profile` 当前的 `repository.py` 已内建一套「分片 + 文件锁 + 内存索引」，本模块将其**抽离为通用能力**，供其余模块复用，避免每个模块各写一份存储逻辑。

### 1.1 职责边界

| 做 | 不做 |
|---|---|
| JSON 文档分片读写、原子写 | 领域数据校验（由业务模块负责） |
| 文件锁与单写串行化 | 业务流程与规则 |
| 内存索引、条件查询、分页 | 生成 / 匹配 / 质检逻辑本身 |
| 集合（命名空间）管理、ID 生成 | 云模型调用 |
| 幂等键去重 | 跨集合事务（仅保证单文档原子） |
| 通用 REST 暴露（运维/调试） | 内容安全与密钥（归 guard） |

### 1.2 关键设计原则

- **基站唯一写入方**：写入集中串行，读多写少，天然适配「单处理基站 + 多教室机」的部署形态。
- **文档型**：无固定表结构，字段 schema 由业务层定义。
- **配置驱动**：集合、索引字段、ID 前缀全部在 `configs/vault/vault.yaml` 声明。
- **可恢复**：启动即重建内存索引；以分片为事实来源，索引损坏可重建。

## 二、存储布局

```
data/
├── students/              集合（命名空间）
│   ├── index.json         集合索引 + 幂等键 + 计数器
│   ├── p_0001.json        单文档分片
│   ├── p_0002.json
│   └── .lock              集合级文件锁
├── resources/
├── feedback/
├── tasks/
└── knowledge/
```

### 2.1 分片结构（envelope 模式）

```json
{
  "id": "p_0001",
  "created_at": "2026-10-19T10:00:00+08:00",
  "updated_at": "2026-10-19T10:00:00+08:00",
  "payload": { "...业务数据..." }
}
```

### 2.2 索引结构

```json
{
  "counter": 4,
  "entries": {
    "p_0001": { "name": "小明", "attributes.disability": "visual", "attributes.severity": "moderate" }
  },
  "idempotency": { "demo-req-1": "p_0001" }
}
```

- `entries` 只冗余**列表/筛选需要的字段**（`index_fields`），列表查询不读分片。
- 索引字段用**点路径**指向 payload（如 `attributes.disability`）。

## 三、架构分层

```
src/kaleido/vault/
├── __init__.py
├── models.py      pydantic 模型：CollectionSpec、Document、QueryResult
├── jsonstore.py   底层：原子写 + 文件锁 + 安全读
├── collection.py  集合：CRUD / 查询 / 分页 / 幂等 / 计数器
├── vault.py       集合注册中心：按配置创建并缓存 Collection
└── api.py         通用 REST 路由
```

调用关系：`vault` → `collection` → `jsonstore` → 文件系统；`config_loader` 复用 `kaleido-common`。

## 四、核心接口（Python）

```python
class JsonStore:
    def __init__(self, root: Path): ...
    def read(self, doc_id: str) -> dict: ...              # 不存在抛 NotFoundError
    def write_atomic(self, doc_id: str, doc: dict) -> None: ...
    def delete(self, doc_id: str) -> None: ...
    def exists(self, doc_id: str) -> bool: ...
    def lock(self): ...                                   # 供 with 使用

class Collection:
    name: str
    def next_id(self) -> str: ...
    def put(self, doc_id: str, payload: dict, *, idempotency_key: str | None = None) -> str: ...
    def get(self, doc_id: str) -> dict: ...
    def delete(self, doc_id: str) -> None: ...
    def find_by_key(self, key: str) -> str | None: ...
    def list(self, filters: dict | None = None, *, page: int = 1, size: int = 20,
             sort: str | None = None) -> tuple[list[dict], int]: ...
    def iter_all(self): ...                               # 迭代分片
    def reindex(self) -> None: ...                        # 以分片为准重建索引

class Vault:
    def __init__(self, root: Path | None = None): ...
    def collection(self, name: str) -> Collection: ...
    def namespaces(self) -> list[str]: ...
```

## 五、并发与可靠性

| 场景 | 策略 |
|---|---|
| 进程内并发 | 每集合 `RLock` 串行化 |
| 多进程 / 外部写入 | `portalocker` 独占锁 + 临时文件 + `os.replace` 原子替换 |
| 分片与索引一致性 | 先写分片、后写索引；ID 分配与幂等登记在同一锁内 |
| 崩溃 / 掉电 | 残留 `.tmp` 不影响；启动时以分片重建缺失索引 |
| 索引损坏 | 忽略并调用 `reindex()` 重建 |
| 分片损坏 | 抛 `StorageError` 并记日志，不污染其它文档 |

## 六、配置

`configs/vault/vault.yaml`：

```yaml
data_dir: data
defaults:
  id_zerofill: 4
  idempotent: false
  envelope: true
collections:
  students:
    id_prefix: p
    id_zerofill: 4
    envelope: false          # 兼容 profile 现有裸文档结构，零迁移
    idempotent: true
    index_fields:
      ["name", "attributes.disability", "attributes.severity", "attributes.cognitive_level"]
  resources:
    id_prefix: r
    id_zerofill: 5
    index_fields: ["type", "tags", "disability", "status"]
  feedback:
    id_prefix: f
  tasks:
    id_prefix: t
  knowledge:
    id_prefix: k
```

## 七、通用 REST 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/vault/<ns>` | 列表，query 传过滤与分页 |
| POST | `/api/v1/vault/<ns>` | 新建（body 为 payload，可选 `client_request_id`） |
| GET | `/api/v1/vault/<ns>/<id>` | 读取 |
| PUT | `/api/v1/vault/<ns>/<id>` | 覆盖更新 |
| DELETE | `/api/v1/vault/<ns>/<id>` | 删除 |
| POST | `/api/v1/vault/<ns>/reindex` | 重建索引 |

> 业务模块仍各自暴露**领域 API**（如 `/api/v1/students`）；vault 通用 API 主要便于运维、调试与后续模块快速接入。

## 八、与 profile 的对接（重点）

**现状**：`profile/repository.py` 自带 `StudentRepository`（分片 + `index.json` + 锁），落盘于 `data/students/`，索引写 `{counter, profiles, requests}`。

**目标**：存储实现下沉到 vault，`StudentRepository` 退化为**薄适配器**，只保留领域语义（集合名、索引字段、ID 前缀、幂等开关）。

```python
class StudentRepository:
    def __init__(self, data_dir=None, vault: Vault | None = None):
        self._collection = (vault or Vault(data_dir)).collection("students")

    def next_id(self):        return self._collection.next_id()
    def find_by_request(self, rid): return self._collection.find_by_key(rid) if rid else None
    def save(self, profile, request_id=None):
        self._collection.put(profile.profile_id, profile.model_dump(), idempotency_key=request_id)
    def get(self, pid):       return StudentEvaluationProfile(**self._collection.get(pid))
    def delete(self, pid):    self._collection.delete(pid)
    def list(self, disability=None, cognitive_level=None, page=1, size=20):
        filters = {}
        if disability:        filters["attributes.disability"] = disability
        if cognitive_level:   filters["attributes.cognitive_level"] = cognitive_level
        return self._collection.list(filters, page=page, size=size)
```

### 8.1 兼容性策略（关键决策）

| 方案 | 说明 | 代价 |
|---|---|---|
| A. `envelope=false`（推荐） | vault 对 students 集合按**裸文档**存储，结构与现状完全一致 | 无需迁移 |
| B. envelope 模式 + 迁移脚本 | 分片改为 `{id, created_at, payload}` 包裹 | 需 `scripts/migrate_vault.py` 一次性迁移 |

默认采用 **A**：`students` 集合 `envelope: false`，保证现有 `data/students/*.json` 零迁移；其它新集合用 envelope 模式以获得统一的时间戳元数据。

### 8.2 对接验收标准

- `tests/profile/*` **不改动**即全部通过。
- `data/students/` 目录结构与索引语义保持兼容。
- 提供 `tests/integration/test_profile_vault.py` 验证跨模块链路（见 `doc/testing.md`）。

## 九、任务拆解

| 步骤 | 内容 | 产出 |
|---|---|---|
| 1 | 底层原子写 + 文件锁 + 安全读 | `jsonstore.py` |
| 2 | 集合：CRUD / 分页 / 幂等 / 计数器 / 重建索引 | `collection.py` |
| 3 | 注册中心 + 配置加载 | `vault.py`、`configs/vault/vault.yaml` |
| 4 | 数据模型 | `models.py` |
| 5 | 通用 REST | `api.py` |
| 6 | 单元 + 并发 + 恢复测试 | `tests/vault/` |
| 7 | profile 适配改造 | `profile/repository.py` |
| 8 | 对接测试 + 本地测试集 | `tests/integration/`、`tests/fixtures/` |

## 十、测试计划（概览）

详见 `doc/testing.md`。要点：单元（CRUD / 分页 / 幂等 / 索引）、并发（多线程 / 多进程写不丢数据）、恢复（索引重建、坏分片隔离）、profile 对接、REST 全链路。

## 十一、风险与对策

| 风险 | 对策 |
|---|---|
| 分片数量增长导致列表变慢 | 列表只读索引；索引字段可配；强制分页 |
| 索引与分片不一致 | 先分片后索引 + 启动校验 + `reindex()` |
| 多进程写丢数据 | `portalocker` 排他锁 + 原子替换 |
| 包裹结构导致 profile 数据不兼容 | 采用 `envelope=false` 或提供迁移脚本 |
| 大文档（资源正文）占内存 | 列表只读索引；正文按需读取 |

## 十二、完成定义（DoD）

- `jsonstore` / `collection` / `vault` / `api` 实现完成，配置驱动。
- profile 改造后**单测不改动全绿**。
- 并发写不丢数据、重启可读、索引可重建。
- 对接测试与本地测试集落地，`pytest` 全绿，`pyright` 0 error，`ruff` 通过。

## 十三、实现状态（已落地）

- **代码**：`src/kaleido/vault/{models,jsonstore,collection,vault,api}.py`；配置 `configs/vault/vault.yaml`。
- **通用配置加载**：`src/kaleido/common/config.py`（供 vault 复用）。
- **profile 改造**：`profile/repository.py` 已成为 vault 适配器，`students` 集合采用 `envelope=false`，**现有数据零迁移**。
- **测试**：`tests/vault/`（jsonstore / collection / vault / concurrency / recovery / api）、`tests/integration/test_profile_vault.py`。
- **本地测试集**：`tests/fixtures/students/samples.json`（valid 矩阵 + edge 边界/非法）、`tests/profile/test_fixtures.py`。
- **脚本**：`scripts/seed_data.py`（本地联调灌数据）。
- **结果**：`pytest` 72 项全绿，`pyright` 0 error。
