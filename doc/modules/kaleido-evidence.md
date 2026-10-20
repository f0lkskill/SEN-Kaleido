# kaleido-evidence 模块现状与架构总结

> 所属项目：SEN-Kaleido
> 模块定位：证据采集层 / 学情数据入口
> 文档版本：v1.0
> 状态：后端已实现，尚未接入 loop 与评价计算
> 记录时间：2026-10-20

---

## 一、在整体架构中的位置

项目采用局域网 C/S 架构：教室机通过浏览器访问处理基站，基站使用 Bottle + waitress 提供统一服务，是唯一写入方；数据统一落入本地 JSON 文档库 `kaleido-vault`，云端大模型调用集中在 `forge`。

```
浏览器（src/web，纯 HTML + JS）
        │ HTTP
        ▼
kaleido.api.app —— 合并各模块 Bottle 子应用
        │
   ┌────┼──────────┬───────────┬──────────┐
 profile  evidence  forge      tasks      vault
 学情画像  证据管理  资源生成    异步任务    存储底座
        │
   ┌────┴────┐
 configs   data/*.json（分片 + index.json + 文件锁）
```

`src/kaleido/api/app.py:41` 中统一创建并共享同一个 `Vault`：

- `profile`、`evidence`、`forge`、`tasks` 共用同一数据目录和存储实例；
- evidence 同时持有 `EvidenceRepository` 与 `StudentRepository`，用于校验“学生是否存在、观测点是否属于该学生框架”；
- 各模块路由通过 `app.merge(...)` 合并，响应统一为 `{code, message, data}`。

### 1.1 后端模块完成度

| 模块 | 状态 | 职责 |
|---|---|---|
| `profile` | 已实现 | 学生档案 + 个性化评价框架 |
| `evidence` | 已实现 | 证据记录、审核、筛选、统计 |
| `forge` | 已实现 | Prompt 生成、LLM 调用、资源落库 |
| `tasks` | 已实现 | 异步任务队列与状态 |
| `vault` | 已实现 | JSON 分片存储、索引、锁、ID |
| `facet` / `match` / `loop` / `guard` | 空壳 | 质检 / 匹配 / 反馈闭环 / 合规 |

---

## 二、证据模块的职责

证据模块位于 **profile（定义“评什么”）** 与未来的 **loop（持续采集课堂数据）** 之间，负责把“学生的一次可观测表现”持久化为可审核、可追溯的记录。

核心设计约束（`src/kaleido/evidence/service.py:3-8`）：

1. 证据必须挂在真实学生上；
2. 必须挂在学生评价框架中真实存在的观测点上；
3. 来源类型必须已登记，且被该观测点声明；
4. 原始媒体（如视频）必须先转为结构化事件；
5. 教师草稿审核通过后，才能作为“已确认证据”使用。

### 2.1 证据记录模型

`src/kaleido/evidence/models.py:16` 定义 `EvidenceRecord`：

| 字段 | 含义 |
|---|---|
| `evidence_id` | 证据 ID，格式 `e_00001` |
| `student_id` | 关联学生档案 ID |
| `observation_key` | 关联评价框架中的观测点 |
| `source_type` | 来源类型键（8 类，见第四节） |
| `title` | 标题，缺省取观测点名称 |
| `content` | 文本描述、评语或结构化事件 |
| `value` | 量化值（得分、时长、正确率） |
| `level` | 对应评分标准等级序号 |
| `attachments` | 附件引用列表（只存路径/文件名，不存二进制） |
| `collected_at` | 采集时间（ISO 字符串） |
| `collector` | 采集人 |
| `note` | 审核意见或补充说明 |
| `status` | `draft` / `verified` / `rejected` |
| `verified_by` / `verified_at` | 审核人与审核时间 |
| `created_at` / `updated_at` | 创建与更新时间 |

请求模型分为 `CreateEvidenceRequest`、`UpdateEvidenceRequest`、`ReviewEvidenceRequest`，见 `src/kaleido/evidence/models.py:38-72`。

### 2.2 三种证据状态与流转

```
新建 ──> draft ──审核通过──> verified
          │  ▲                  │
          │  └──驳回────────────┤
          └────> rejected <─────┘
```

- `create` 一律生成 `draft`（`src/kaleido/evidence/service.py:96`）；
- `review` 只接受 `verified` / `rejected`（`src/kaleido/evidence/service.py:152`）；
- `verified` 状态禁止直接修改，必须先驳回（`src/kaleido/evidence/service.py:143`）；
- `delete` 不限制状态，已审核证据也可直接删除，目前没有审计保留机制。

---

## 三、评价框架与证据的绑定关系

证据不是独立数据表，它依赖 profile 生成的四级评价框架：

```
EvaluationFramework（框架）
  └─ Indicator（指标）
       └─ ObservationItem（观测点）
            └─ Rubric（评分标准）
```

- `ObservationItem.evidence_sources` 声明该观测点接受哪些证据来源（`src/kaleido/profile/models/evaluation.py:27`）；
- 框架生成时从 `configs/profile/evaluation_frameworks.yaml` 拷贝来源白名单（`src/kaleido/profile/framework.py:125`）；
- 创建证据时，服务层遍历 `framework.indicators[].observations[]` 定位观测点，找不到即拒绝（`src/kaleido/evidence/service.py:58`）。

当前公共评价框架包含两个维度、两个指标、两个观测点：

| 维度 | 指标 | 观测点 | 证据来源 |
|---|---|---|---|
| 课堂参与 | 上课参与度 | `class_engagement` 课堂参与程度 | `classroom_observation` / `teacher_rating` |
| 练习质量 | 练习完成质量 | `practice_completion` 练习完成质量 | `work_sample` / `item_response` / `teacher_rating` |

---

## 四、证据来源体系

来源定义在 `configs/profile/evidence_sources.yaml`，配置驱动、可热重载。当前共 8 类：

| key | 名称 | modality | 加工方式 | 成本 | 特殊约束 |
|---|---|---|---|---|---|
| `item_response` | 试题作答 | structured | 自动或人工 | 低 | 客观题可自动判分 |
| `classroom_observation` | 课堂观察 | structured | 人工 | 低 | 教师勾选 + 评语 |
| `video_event` | 视频事件 | raw_media | 人工或 LLM | 高 | **必须先切段结构化** |
| `work_sample` | 作品/作业样本 | artifact | 人工 | 中 | 附件引用 |
| `teacher_rating` | 教师评分 | structured | 人工 | 低 | 结构化等级/分数 |
| `parent_feedback` | 家长反馈 | text | 人工或 LLM | 中 | 文本转结构化 |
| `rehab_record` | 康复师记录 | structured | 人工 | 中 | 康复进展 |
| `system_log` | 系统埋点 | structured | 自动 | 低 | 播放/点击/错题率 |

关键规则：

- **全局登记**：`source_type` 必须存在于 `evidence_sources.yaml`，否则返回 400；
- **观测点白名单**：观测点只接受自身 `evidence_sources` 中声明的来源；
- **视频强制结构化**：`requires_segmentation: true` 且 `content` 为空时拒绝（`src/kaleido/evidence/service.py:79`）；
- **未声明来源的观测点**：设计文档要求“不可评价”，但当前代码仅在 `observation.evidence_sources` 非空时限制（`src/kaleido/evidence/service.py:74`）。空列表目前等同于“接受任意已登记来源”，与设计存在偏差。

来源定义通过 `GET /api/v1/evaluation/evidence-sources` 暴露给前端（`src/kaleido/profile/api.py:111`），前端用于把内部键映射为中文名（`src/web/assets/js/core/api.js:126`、`src/web/assets/js/core/format.js:85`）。

---

## 五、调用链与存储

### 5.1 HTTP API

`src/kaleido/evidence/api.py` 提供以下端点：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/evidence` | 新增证据草稿 |
| GET | `/api/v1/evidence` | 按学生/观测点/来源/状态筛选 |
| GET | `/api/v1/evidence/summary` | 按状态/来源/观测点汇总 |
| GET | `/api/v1/evidence/{id}` | 读取单条 |
| PUT | `/api/v1/evidence/{id}` | 更新草稿/被驳回记录 |
| POST | `/api/v1/evidence/{id}/review` | 审核通过或驳回 |
| DELETE | `/api/v1/evidence/{id}` | 删除 |

查询参数包括 `student_id`、`observation_key`、`source_type`、`status`、`page`、`size`。

### 5.2 新增证据的完整链路

```
POST /api/v1/evidence
  → EvidenceService.create()
      → StudentRepository.get(student_id)              # 学生必须存在
      → 遍历 framework.indicators[].observations[]     # 观测点必须属于该学生
      → load_config("evidence_sources")                # 来源必须已登记
      → 检查 observation.evidence_sources 白名单
      → 检查视频类来源是否已结构化
      → EvidenceRepository.next_id()                   # e_00001
      → Collection.put(record)                         # vault 原子写
          → data/evidence/e_00001.json
          → data/evidence/index.json
```

### 5.3 存储细节

`configs/vault/vault.yaml:26` 中 `evidence` 集合配置：

- ID 前缀 `e`，5 位补零；
- 默认 `envelope: true`，磁盘文档结构为 `{id, created_at, updated_at, payload}`；
- 索引字段：`student_id`、`observation_key`、`source_type`、`status`、`collected_at`；
- 未启用幂等键，同一证据重复提交不会被自动去重。

`EvidenceRepository` 是薄适配器（`src/kaleido/evidence/repository.py:12`），把领域操作映射到 `vault.collection("evidence")`：

- `list()` 使用 `list_full()`，按索引过滤分页后回读完整文档；
- 写入依赖 vault 的文件锁 + 原子替换，支持多教室机并发。

### 5.4 当前实际使用情况

- `data/evidence/` 目前只有 `.lock`，**没有任何真实证据记录**；
- `data/students/` 有 12 条档案，说明证据功能刚落地、尚未进入日常使用；
- 前端代码中目前只看到“证据来源元数据”调用，没有证据 CRUD 视图；
- `tests/evidence/` 只有 `test_service.py`，覆盖创建、来源校验、观测点校验、审核流转、更新限制、筛选与统计，**没有 evidence API 层测试**。

---

## 六、模块关系

| 关系 | 说明 |
|---|---|
| `profile → evidence` | profile 生成评价框架与观测点；evidence 读取学生档案，校验观测点与来源白名单 |
| `evidence → vault` | 证据落盘到 `data/evidence`，通过 vault 索引分页与并发控制 |
| `evidence → loop` | 设计上 loop 负责课堂采集并把结果写入 evidence；当前 loop 为空，证据只能由人工或外部脚本调用 API 写入 |
| `evidence → facet` | 目前无直接关系；将来可用证据审核结果反哺资源质量校验 |
| `evidence → match` | 目前无直接关系；证据汇总可作为学生能力变化输入 |
| `forge` | 只用 profile 属性生成资源，不消费 evidence |
| `tasks` | 目前没有证据相关任务类型，证据写入是同步的 |
| `guard` | 空壳，证据接口尚未接入鉴权与内容安全 |
| 前端 | 仅消费 evidence-sources 元数据，证据管理 UI 尚未接入 |

设计意图是：**profile 定义标尺，loop 采集数据，evidence 保存证据，facet/match/forge 再消费数据**。目前链路只完成了 profile → evidence 这一段。

---

## 七、设计优点

- 证据强绑定学生评价框架，避免“有数据但无法解释属于哪个评价点”；
- 来源体系配置化，新增来源只改 YAML；
- 草稿/审核/驳回状态机保证教师确认权；
- 视频必须先结构化，避免原始媒体直接进模型；
- 复用 vault 的原子写、文件锁、索引，与 profile 数据天然一致。

---

## 八、缺口与风险

按优先级排列：

1. **证据未接入 loop**：没有自动采集、批量导入、前后测对照，目前只能手工调用 API。
2. **证据不参与评价计算**：记录的 `value` / `level` 没有汇总成学生维度指数，profile 的 `dimension_indexes` 仍是建档时由属性推导的静态值。
3. **分页排序问题**：`EvidenceService.list()` 先让 vault 分页，再对当前页按 `collected_at` 排序（`src/kaleido/evidence/service.py:136-137`），跨页并非全局按采集时间倒序；应在索引层排序后再分页。
4. **空 `evidence_sources` 语义不一致**：文档要求“未声明来源即不可评价”，代码却允许任意已登记来源。
5. **无证据幂等**：`evidence` 集合 `idempotent: false`，重复提交会产生多条相同证据。
6. **附件无上传/存储能力**：`attachments` 只是字符串引用，没有文件上传、校验、清理接口。
7. **审核与删除缺少审计**：删除已审核证据无留痕；更新只记录 `updated_at`，没有版本历史。
8. **无 API 级测试与来源配置校验**：来源 YAML 字段缺失不会在启动时显式报错；evidence API 的异常映射未测试。
9. **`value` / `level` 未按 rubric 校验**：`level` 可以写入不存在的等级，`value` 没有范围约束。
10. **`summary` 使用 `size=1000000`**：数据量大时会把整个索引拉进内存，应改为索引聚合或专门计数。

---

## 九、结论

证据模块已经具备 **“学生—观测点—来源—审核”** 的完整领域闭环和可用的 CRUD API，但它是**孤立的写入端**：上游依赖 profile 的评价框架，下游本应接到 loop 与评价计算，目前尚未接通；数据目录也还没有真实证据。

下一阶段优先事项：

1. 接入 `loop` 采集，打通自动/批量证据写入；
2. 把证据汇总回画像指数，形成“采集 → 评价 → 调整”的闭环；
3. 修正分页排序与空来源白名单语义；
4. 补充 evidence API 测试与来源配置校验；
5. 对接前端证据管理视图。

---

## 十、关键文件索引

| 文件 | 作用 |
|---|---|
| `src/kaleido/evidence/models.py` | 证据实体与请求模型 |
| `src/kaleido/evidence/repository.py` | vault 集合适配器 |
| `src/kaleido/evidence/service.py` | 校验、状态流转、筛选统计 |
| `src/kaleido/evidence/api.py` | Bottle 路由与异常映射 |
| `src/kaleido/api/app.py` | 统一应用装配与共享 Vault |
| `src/kaleido/profile/models/evaluation.py` | 评价框架与观测点模型 |
| `src/kaleido/profile/framework.py` | 框架生成与来源白名单注入 |
| `src/kaleido/profile/api.py` | 证据来源元数据接口 |
| `configs/profile/evidence_sources.yaml` | 8 类证据来源定义 |
| `configs/profile/evaluation_frameworks.yaml` | 公共指标与观测点来源声明 |
| `configs/vault/vault.yaml` | evidence 集合索引与 ID 配置 |
| `tests/evidence/test_service.py` | 证据服务单元测试 |
