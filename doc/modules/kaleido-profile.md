# kaleido-profile 模块开发规划

> 所属项目：SEN-Kaleido
> 模块定位：学情画像层（闭环输入层）
> 文档版本：v1.0
> 状态：规划中（作为项目开发起点）

---

## 一、模块概述

`kaleido-profile` 是整个 SEN-Kaleido 闭环的**输入层**与**数据契约层**。它负责把特殊学生的非结构化描述（障碍类型、程度、认知水平、感官偏好、康复目标等）转化为下游所有模块可计算的**标准化学情标签向量**。

下游 `forge`（生成）、`facet`（质检）、`match`（匹配）、`loop`（反馈）全部以本模块输出的标签向量作为输入契约。因此本模块必须最先开发、最稳定、最可测。

## 二、目标与范围

### 2.1 本模块做什么

- 定义学生画像的数据模型与维度枚举。
- 以配置文件驱动各维度的取值与映射规则。
- 通过分层规则引擎，由障碍类型与程度推导默认适配约束与 Prompt 模板键。
- 输出统一 JSON 标签向量，持久化到 `kaleido-vault`。
- 提供增删查改与"规则推导"接口供基站与其他模块调用。

### 2.2 本模块不做什么

- 不调用云端大模型（零外部依赖）。
- 不生成任何学习资源（属于 `forge`）。
- 不做推荐排序（属于 `match`）。
- 不制定特教专业标准，只负责把已确定的规则工程化、可配置化。

## 三、数据模型设计

### 3.1 维度枚举

| 枚举 | 取值 |
|---|---|
| 障碍类型 `DisabilityType` | `visual` 视力障碍 / `hearing` 听力障碍 / `intellectual` 智力障碍 / `autism` 自闭症 |
| 障碍程度 `SeverityLevel` | `mild` 轻度 / `moderate` 中度 / `severe` 重度 |
| 认知等级 `CognitiveLevel` | `preschool` 学前 / `primary_low` 小学低段 / `primary_high` 小学高段 / `vocational` 职教 |
| 感官偏好 `SensoryPreference` | `visual_first` 视觉优先 / `audio_first` 听觉优先 / `tactile_aided` 触觉辅助 / `mixed` 图文结合 |
| 康复目标 `RehabGoal` | `language` 语言 / `sensory_integration` 感统 / `social` 社交 / `cognitive` 认知训练（可多选） |
| 学习节奏 `LearningPace` | `fast` 快 / `medium` 中 / `slow` 慢 |

### 3.2 核心实体 `StudentProfile`

| 字段 | 类型 | 说明 |
|---|---|---|
| `profile_id` | str | 画像唯一 ID |
| `name` | str | 学生姓名/化名 |
| `disability` | DisabilityType | 障碍类型（必填） |
| `severity` | SeverityLevel | 障碍程度 |
| `cognitive_level` | CognitiveLevel | 认知等级 |
| `sensory_preference` | SensoryPreference | 感官偏好（可缺省，由规则推导） |
| `rehab_goals` | list[RehabGoal] | 康复目标（可多选） |
| `learning_pace` | LearningPace | 学习节奏 |
| `adaptation_constraints` | dict | 由规则引擎推导的适配约束 |
| `prompt_template_key` | str | 关联的 Prompt 模板键 |
| `created_at` / `updated_at` | str | 时间戳 |

### 3.3 输出标签向量示例

```json
{
  "profile_id": "p_0001",
  "disability": "visual",
  "severity": "moderate",
  "cognitive_level": "primary_low",
  "sensory_preference": "audio_first",
  "rehab_goals": ["language", "cognitive"],
  "learning_pace": "slow",
  "adaptation_constraints": {
    "format": "voice_first",
    "sentence_length_max": 15,
    "avoid_visual_ref": true
  },
  "prompt_template_key": "visual_layer"
}
```

## 四、配置驱动设计

所有维度取值与映射规则放在 `configs/profile/` 下，教师与教研人员可不改代码调整参数。

### 4.1 `configs/profile/disability_rules.yaml`

```yaml
visual:
  name: 视力障碍
  defaults:
    sensory_preference: audio_first
  constraints:
    format: voice_first
    sentence_length_max: 15
    avoid_visual_ref: true
  prompt_template: visual_layer

hearing:
  name: 听力障碍
  defaults:
    sensory_preference: visual_first
  constraints:
    require_caption: true
    visual_priority: true
  prompt_template: hearing_layer

intellectual:
  name: 智力障碍
  defaults:
    sensory_preference: mixed
  constraints:
    step_by_step: true
    add_emoji: true
    sentence_length_max: 12
  prompt_template: intellectual_layer

autism:
  name: 自闭症
  defaults:
    sensory_preference: mixed
  constraints:
    short_sentence: true
    simple_vocab: true
    visual_aid: true
  prompt_template: autism_layer
```

### 4.2 配置加载规则

- 启动时加载并校验配置，配置缺失字段时报错。
- 支持按障碍类型 + 程度覆盖约束（程度越重，约束越严格）。
- 配置热更新：提供重载接口，便于试点中调参。

## 五、规则引擎设计

**输入**：障碍类型、程度、认知等级、可选感官偏好。
**输出**：`adaptation_constraints` + `prompt_template_key`。

**推导流程**：
1. 按 `disability` 载入基础约束与模板键。
2. 按 `severity` 叠加严格化规则（如 `severe` 时 `sentence_length_max` 进一步收紧）。
3. 若用户显式指定 `sensory_preference`，覆盖默认值；否则采用配置默认。
4. 按 `cognitive_level` 调整词汇难度与步骤粒度。
5. 合并 `rehab_goals` 生成附加约束标签。

**原则**：规则可解释、可追溯，每次推导保留命中规则记录，便于教师理解"为什么得到这些约束"。

## 六、接口设计

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/profile` | 新建画像，返回含推导约束的标签向量 |
| GET | `/api/profile/{profile_id}` | 查询单个画像 |
| GET | `/api/profile` | 列表 / 按障碍类型、认知等级筛选 |
| PUT | `/api/profile/{profile_id}` | 更新画像并重新推导 |
| POST | `/api/profile/{profile_id}/derive` | 仅按当前输入重新推导约束 |
| POST | `/api/profile/reload-config` | 热重载配置文件 |

接口由 `kaleido-api`（Bottle）统一挂载，本模块只提供路由处理函数。

## 七、模块内目录结构

```
src/kaleido/profile/
├── __init__.py
├── models.py         数据模型与枚举
├── config_loader.py  配置加载与校验
├── rules.py          分层规则引擎
├── service.py        业务逻辑（组合规则与存储）
├── repository.py     持久化访问（对接 kaleido-vault）
└── api.py            Bottle 路由处理函数
```

## 八、任务拆解（开发步骤）

| 步骤 | 内容 | 产出 |
|---|---|---|
| 1 | 定义数据模型与枚举 | `models.py` |
| 2 | 实现配置加载与校验 | `config_loader.py`、`configs/profile/*.yaml` |
| 3 | 实现分层规则引擎 | `rules.py` |
| 4 | 实现存储访问（JSON 落盘 + 加锁） | `repository.py` |
| 5 | 实现业务服务层 | `service.py` |
| 6 | 挂载 API 路由 | `api.py` |
| 7 | 编写单元测试（覆盖四大障碍类型） | `tests/profile/` |
| 8 | 编写使用说明 | 本文档补充"快速开始" |

## 九、测试计划

- **枚举与模型**：字段校验、必填项、非法取值。
- **配置加载**：正常加载、缺字段报错、热重载。
- **规则引擎**：四大障碍类型 × 三种程度，断言推导出的约束符合预期；显式偏好覆盖默认值。
- **接口**：创建/查询/更新/推导全链路。
- **持久化**：并发写加锁不丢数据、重启后可读取。

## 十、依赖与接口契约

- 依赖 `kaleido-common`（配置加载、日志、公共数据模型基类）。
- 依赖 `kaleido-vault`（JSON 文档库读写）。
- **对外契约**：稳定输出 3.3 节定义的标签向量结构，字段只增不删，变更需版本化。
- 不依赖任何云端服务，可离线运行与测试。

## 十一、风险与对策

| 风险 | 对策 |
|---|---|
| 维度定义与特教专家意见不一致 | 全部走配置文件，专家可复核；预留维度扩展 |
| 程度叠加规则复杂导致难维护 | 规则显式化、可追溯，编写规则命中日志 |
| 下游误用不完整画像 | 提供校验接口，缺关键字段时返回明确错误 |
| 配置被随意改动 | 配置纳入版本管理，重载保留历史快照 |

## 十二、完成定义（DoD）

- 数据模型、配置加载、规则引擎、存储、API、测试全部完成。
- 四大障碍类型的标签向量推导结果经特教教师抽样确认。
- 通过 ruff 检查与 pytest 全绿。
- 输出标签向量结构与下游模块（forge）达成一致。
