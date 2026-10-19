# kaleido-profile 模块开发规划

> 所属项目：SEN-Kaleido
> 模块定位：学生评价模型（学情画像层 / 闭环输入层）
> 文档版本：v2.0
> 状态：规划中（作为项目开发起点）

---

## 一、模块概述

`kaleido-profile` 是整个 SEN-Kaleido 闭环的**输入层**与**数据契约层**，承担**学生评价模型**的构建。它不止定义"学生是谁"，还定义"如何评价这个学生"：

- **画像视角**：把特殊学生的障碍类型、程度、认知水平、感官偏好、康复目标等转化为标准化的学生实例。
- **评价视角**：为学生生成个性化的**评价内容框架**（评价维度 → 指标 → 观测点 → 评分标准），供课堂数据采集与效果验证使用。

整个模块围绕一个中心组织：**学生评价本体（Student Evaluation Ontology）**，分为类型层、属性层、评价框架层三层，评价框架由引擎按前两层实例化生成。

下游 `forge`、`facet`、`match`、`loop` 全部以本模块输出的学生实例与评价框架作为输入契约，因此本模块必须最先开发、最稳定、最可测。

### 1.1 数据来源与模块分工（重要）

本模块不采集课堂教学数据，也不自动"给评价"。必须区分三类东西：

| 类别 | 内容 | 来源 | 归属 |
|---|---|---|---|
| 静态属性 | 障碍类型、程度、认知等级、感官偏好、康复目标、学习节奏 | 建档时录入（入学评估 / 教师 / 家长） | 本模块，一次性 |
| 评价框架 | 评什么、怎么评、评分标准 | 配置 + 规则引擎生成 | 本模块，一次性定义 |
| 动态评价数据 | 课堂参与、答题结果、行为表现、康复进展 | 随教学持续采集 | `kaleido-loop`，非本模块 |

要点：

- **静态属性必须有人工建档**：系统无法自动得知"某学生是自闭症、中度"，建档时录入一次即可。
- **本模块产出的是"评价框架"（标尺），不是"评价结果"（数据）**。教师课堂评分、学生答题数据由 `loop` 采集。
- **特教评价不能只看答题自动评分**：依据申报书难点 2 与研究内容 4，数据需为前后测成绩、课堂观察、学生行为表现、教师反馈、家长评价等多源，量化与质性结合。评价框架的职责就是把这些多源数据统一成一张采集清单。
- 因此"画像自动生成"的说法不准确：系统自动完成的是**从已录入属性推导评价框架与适配约束**；属性本身仍需建档录入。

## 二、目标与范围

### 2.1 本模块做什么

- 定义学生类型分类体系（类型层）。
- 定义学生多维属性（属性层），含静态属性与动态基线快照。
- 定义评价内容框架：评价维度、指标、观测点、评分标准（评价框架层）。
- 由分层规则引擎按"类型 + 属性"实例化出个性化评价框架。
- 输出统一 JSON 学生实例（含评价框架），持久化到 `kaleido-vault`。
- 提供增删查改、框架预览、评分标准查询等接口。

### 2.2 本模块不做什么

- 不调用云端大模型（零外部依赖）。
- 不生成任何学习资源（属于 `forge`）。
- 不做推荐排序（属于 `match`）。
- 不执行课堂数据采集与统计（属于 `loop`，本模块只提供采集清单即评价框架）。
- 不制定特教专业标准，只负责把已确定的规则工程化、可配置化。

## 三、架构总览：一个中心 + 三层

```
        ┌───────────────────────────────────────────────┐
        │        学生评价本体 (Evaluation Ontology)        │
        └───────────────────────────────────────────────┘
             │                │                    │
     ┌───────┴──────┐  ┌──────┴──────┐  ┌──────────┴────────┐
     │  ① 类型层     │  │  ② 属性层    │  │  ③ 评价框架层       │
     │  StudentType │  │ Attributes  │  │ EvaluationFramework│
     │  障碍分类体系  │  │  多维属性    │  │ 维度→指标→观测点→标准│
     └───────┬──────┘  └──────┬──────┘  └──────────┬────────┘
             └────────┬───────┘                    │
                      │       框架生成引擎           │
                      │  (类型+属性 → 个性化评价框架) │
                      └────────────┬───────────────┘
                                   │
                    StudentEvaluationProfile（学生实例 + 专属评价框架）
```

三层解耦：**类型层**是分类体系，**属性层**是一个学生的多维数据，**评价框架层**是"评价什么、怎么评、按什么标准评"。评价框架不写死，由引擎根据前两层实例化。

## 四、① 类型层（StudentType）

配置驱动的分类体系，支持扩展、多重障碍与共病：

```yaml
student_types:
  visual:
    name: 视力障碍
    parent: null
    tags: [sensory, visual]
  hearing:
    name: 听力障碍
    tags: [sensory, auditory]
  intellectual:
    name: 智力障碍
    tags: [cognitive]
  autism:
    name: 自闭症
    tags: [developmental, social]
```

关键点：类型不是孤立枚举，而是带 `parent` 与 `tags` 的树/图，支持组合类型表达"多重障碍"，新增类型只改配置。

## 五、② 属性层（Attributes）

| 类别 | 维度 | 示例 |
|---|---|---|
| 静态 | 障碍程度 | 轻度 / 中度 / 重度 |
| 静态 | 认知等级 | 学前 / 小学低段 / 小学高段 / 职教 |
| 静态 | 感官偏好 | 视觉优先 / 听觉优先 / 触觉辅助 / 图文结合 |
| 静态 | 康复目标 | 语言 / 感统 / 社交 / 认知（多选） |
| 静态 | 学习节奏 | 快 / 中 / 慢 |
| 动态 | 能力基线 | 当前识字量、理解水平等 |
| 动态 | 病史 / 辅具 | 助听器、盲杖等（可选、脱敏） |

动态属性是评价的**起点快照**，与 `loop` 采集的课后数据形成前后对照。

## 六、③ 评价框架层（核心）

采用**四级树结构**：

```
评价维度 Dimension
  └─ 指标 Indicator
       └─ 观测点 ObservationItem
            └─ 评分标准 Rubric
```

- **维度（当前阶段）**：因课题研究方向尚未确定，暂不启用各障碍类型的专有指标，统一使用**两个公共维度**——课堂参与、练习质量。
- **指标（公共）**：所有学生共用两项公共标准——**上课参与度**（课堂参与维度）、**练习完成质量**（练习质量维度）。后续课题确定后再按障碍类型扩展专有维度与指标。
- **观测点**：指标的可观测行为，是数据采集的落点，明确"看什么、记什么"。
- **评分标准（Rubric）**：等级描述（如 未达成/初步/基本/熟练 四级）+ 观测证据要求，保证不同教师评价口径一致。

### 6.1 数据来源的定义（以观测点倒推证据）

原则：**先定"评什么"，再定"用什么证明"**，而不是拿一堆视频/试题去问系统能评什么。未声明证据来源的观测点是**不可评价的空指标**。

每个观测点必须声明 `evidence_sources`，只有登记过的来源才会被 `kaleido-loop` 采集。

证据类型枚举（配置维护）：

| key | 说明 | 加工方式 |
|---|---|---|
| `item_response` | 试题作答 | 客观题自动判分；主观题人工 / LLM 辅助 |
| `classroom_observation` | 课堂观察 | 教师勾选 + 评语 |
| `video_event` | 视频事件 | 原始视频先切段为"时间戳 + 行为标签" |
| `work_sample` | 作品 / 作业样本 | 人工或辅助 |
| `teacher_rating` | 教师评分 | 结构化 |
| `parent_feedback` | 家长反馈 | 文本 → 结构化 |
| `rehab_record` | 康复师记录 | 结构化 |
| `system_log` | 系统埋点 | 自动（播放时长 / 点击 / 错题率） |

关键限制：

- 课堂录像、视频是**原始媒体**，禁止直接送模型"猜"，必须先转为**结构化事件**（时间戳 + 行为标签）再作为证据。
- 视频成本高、合规敏感，**只在关键指标启用**，不能全量采集。
- 试题作答、系统埋点等天然结构化、低成本的来源可常态化使用。

示例：

| 指标 | 观测点 | 证据来源 | 方式 |
|---|---|---|---|
| 上课参与度 | 课堂参与程度 | `classroom_observation` / `teacher_rating` | 质性 |
| 练习完成质量 | 练习完成质量 | `work_sample` / `item_response` / `teacher_rating` | 量化 |

### 6.2 是否使用大模型（LLM）

| 环节 | 是否用 LLM | 原因 |
|---|---|---|
| 属性 → 标签向量 | 不用，规则/枚举 | 障碍类型→约束是专家确定的映射，须可解释、可复现 |
| 评价框架生成 | 不用，配置 + 规则 | 评什么、怎么评必须稳定、可复核 |
| 非结构化输入 → 属性抽取 | 可用（辅助） | 老师口述、访谈、观察笔记 → 结构化字段，需教师确认 |
| 开放题评分 / 视频事件分析 | 可用（辅助，归 `kaleido-loop`） | 质性数据辅助分析，需教师确认 |

结论：本模块主体**规则驱动、无 LLM**，保证可解释、可复现、零推理成本；LLM 仅用于边界处的自然语言抽取与质性数据辅助分析，且遵循"AI 建议 + 教师确认"。

## 七、框架生成引擎

```
输入 StudentEvaluationProfile
      │
      ├─ 载入公共指标模板（上课参与度、练习完成质量）
      ├─ 按 rehab_goals 对相关维度加权
      ├─ 按 severity 提升观测频率并压缩评分等级
      └─ 输出 公共评价框架（指标清单 + 权重 + 观测频率 + 评分方式）
```

评价方式同时支持**量化**（计数/时长/得分）与**质性**（观察描述/等级），对应课题"量化与质性结合法"。观测频率可按每课/每周/每阶段配置。`severity=severe` 时观测频率提升为每课、评分等级从四级降到三级，避免评价压力过大。

## 八、数据模型（Pydantic）

```python
class StudentType(BaseModel):        # 类型层
    key: str
    name: str
    parent: str | None
    tags: list[str]

class StudentAttributes(BaseModel):  # 属性层
    disabilities: list[str]          # 多障碍时为多项，首项视为主障碍
    severity: str
    cognitive_level: str
    sensory_preference: str | None
    rehab_goals: list[str] = []
    learning_pace: str
    baseline: dict | None = None

class Rubric(BaseModel):
    level: int
    label: str
    description: str
    evidence: str

class ObservationItem(BaseModel):
    key: str
    name: str
    method: str                  # quantitative / qualitative
    frequency: str               # per_lesson / weekly / phase
    evidence_sources: list[str]  # 证据类型，见 6.1 枚举
    rubrics: list[Rubric]

class Indicator(BaseModel):
    key: str
    name: str
    dimension: str
    observations: list[ObservationItem]

class EvaluationFramework(BaseModel):
    framework_id: str
    dimensions: list[str]
    indicators: list[Indicator]
    weights: dict[str, float]
    prompt_template_key: str

class StudentEvaluationProfile(BaseModel):
    profile_id: str
    name: str
    attributes: StudentAttributes
    framework: EvaluationFramework
    created_at: str | None
    updated_at: str | None
```

## 九、配置驱动设计

```
configs/profile/
├── student_types.yaml         类型树
├── attributes.yaml            属性维度与取值
├── evidence_sources.yaml      证据类型枚举
├── evaluation_frameworks.yaml 公共评价维度与指标模板
└── rubrics/                   评分标准
    ├── participation.yaml
    └── practice.yaml
```

- 启动时加载并校验配置，缺失字段报错。
- 当前阶段为公共框架；后续可按障碍类型 + 程度叠加覆盖（程度越重约束越严格）。
- 提供热重载接口，便于试点中调参。
- 配置纳入版本管理，重载保留历史快照。

## 十、接口设计（API 对接）

### 10.1 通用约定

- **Base URL**：`http://<基站IP>:8080/api/v1`
- **请求头**：`Content-Type: application/json; charset=utf-8`；`X-Auth-Token: <token>`
- **鉴权**：由 `kaleido-guard` 签发 token，教师机首次访问配对一次后本地保存；局域网内可配置关闭，默认开启。
- **统一响应包裹**：`{ "code": 0, "message": "ok", "data": { } }`
- **时间格式**：ISO8601，如 `2026-10-19T12:00:00+08:00`
- **幂等**：创建接口支持 `client_request_id` 去重。

### 10.2 端点清单

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/students` | 建立学生 + 属性，返回实例化评价框架 |
| GET | `/students/{profile_id}` | 查询学生及评价框架 |
| GET | `/students` | 列表 / 按障碍类型、认知等级筛选，分页 |
| PUT | `/students/{profile_id}` | 更新属性并重新生成框架 |
| DELETE | `/students/{profile_id}` | 删除学生 |
| GET | `/evaluation/dimensions` | 查询维度体系 |
| POST | `/evaluation/framework` | 按属性生成框架（不落库，仅预览） |
| GET | `/evaluation/rubric/{indicator}` | 查询指标评分标准 |
| POST | `/profile/reload-config` | 热重载配置文件 |

### 10.3 请求 / 响应示例

`POST /students` 请求：

```json
{
  "client_request_id": "req-8f2c",
  "name": "小明",
  "attributes": {
    "disabilities": ["visual"],
    "severity": "moderate",
    "cognitive_level": "primary_low",
    "sensory_preference": null,
    "rehab_goals": ["language", "cognitive"],
    "learning_pace": "slow"
  },
  "generate_framework": true
}
```

响应 `201`：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "profile_id": "p_0001",
    "name": "小明",
    "attributes": {
      "disabilities": ["visual"],
      "severity": "moderate",
      "cognitive_level": "primary_low",
      "sensory_preference": "audio_first",
      "rehab_goals": ["language", "cognitive"],
      "learning_pace": "slow"
    },
    "framework": {
      "framework_id": "fw_p_0001",
      "dimensions": ["participation", "practice"],
      "indicators": [
        { "key": "class_participation", "name": "上课参与度", "dimension": "participation" },
        { "key": "practice_quality", "name": "练习完成质量", "dimension": "practice" }
      ],
      "weights": {
        "participation": 0.5,
        "practice": 0.5
      },
      "prompt_template_key": "visual_layer"
    },
    "created_at": "2026-10-19T12:00:00+08:00"
  }
}
```

注意：`sensory_preference` 传入 `null` 时返回的是规则推导值 `audio_first`——**入参可缺省，出参必完整**。

### 10.4 错误码

| code | HTTP | 含义 |
|---|---|---|
| 0 | 200/201 | 成功 |
| 1001 | 400 | 参数校验失败（字段缺失/取值非法） |
| 1002 | 404 | 学生不存在 |
| 1003 | 409 | `client_request_id` 重复（幂等去重） |
| 1004 | 500 | 配置缺失或非法 |
| 1005 | 500 | 存储写入失败 |

错误响应仍用同一包裹，例如：`{ "code": 1001, "message": "attributes.disability 取值非法", "data": null }`

### 10.5 Bottle 路由实现要点

```python
from bottle import Bottle, request, response

app = Bottle()

@app.post("/api/v1/students")
def create_student():
    payload = request.json or {}
    try:
        result = service.create_student(payload)
    except ValidationError as e:
        response.status = 400
        return {"code": 1001, "message": str(e), "data": None}
    response.status = 201
    return {"code": 0, "message": "ok", "data": result}
```

- 路由只做参数解析与异常映射，业务在 `service.py`。
- 统一异常中间件把 `ValidationError / NotFound / ConfigError` 映射为上述错误码。

### 10.6 与 vault 的落盘

存储实现已下沉到 `kaleido-vault`，`repository.py` 现为**薄适配器**：

- 集合：`students`（`envelope=false`，裸文档，与既有数据零迁移）。
- 每个学生一个分片：`data/students/p_0001.json`
- 索引文件：`data/students/index.json`（`entries` 存 `name / attributes.disability / attributes.severity / attributes.cognitive_level`，`idempotency` 存幂等键，`counter` 存自增）
- 写入经 vault 的 `portalocker` 文件锁 + 原子替换，避免多教室并发丢数据
- 列表查询只读内存索引；`get` 未命中分片再读文件

详见 `doc/modules/kaleido-vault.md` 第八节。

### 10.7 教室机 JS 调用示例

```javascript
const res = await fetch("/api/v1/students", {
  method: "POST",
  headers: { "Content-Type": "application/json", "X-Auth-Token": token },
  body: JSON.stringify({ name, attributes, generate_framework: true })
});
const { code, message, data } = await res.json();
if (code !== 0) { alert(message); return; }
```

## 十一、模块内目录结构

```
src/kaleido/profile/
├── __init__.py
├── models/
│   ├── taxonomy.py      类型体系实体
│   ├── student.py       学生与属性实体
│   └── evaluation.py    评价框架实体
├── config_loader.py     配置加载与校验
├── taxonomy.py          类型层加载
├── attributes.py        属性层校验与规范化
├── framework.py         评价框架生成引擎
├── repository.py        持久化（对接 kaleido-vault）
├── service.py           业务逻辑
└── api.py               Bottle 路由处理函数
```

## 十二、与下游模块的关系

- **`kaleido-loop`**：直接消费评价框架的观测点做数据采集与统计，评价框架 = 采集清单，支持前后测对照。
- **`kaleido-forge` / `kaleido-match`**：用属性层做资源适配；评价框架的指标可反向指导生成重点。
- **`kaleido-facet`**：质量评价与评价框架共用 `rubrics/` 标准体系，保证"资源质量"与"学生评价"口径一致。

## 十三、任务拆解（开发步骤）

| 步骤 | 内容 | 产出 |
|---|---|---|
| 1 | 类型层：定义类型树与加载 | `models/taxonomy.py`、`taxonomy.py`、`student_types.yaml` |
| 2 | 属性层：校验与规范化 | `models/student.py`、`attributes.py`、`attributes.yaml` |
| 3 | 评价框架实体与 Rubric 体系 | `models/evaluation.py`、`configs/profile/rubrics/*.yaml` |
| 4 | 框架生成引擎 | `framework.py`、`evaluation_frameworks.yaml` |
| 5 | 存储访问（JSON 分片 + 加锁 + 索引） | `repository.py` |
| 6 | 业务服务层 | `service.py` |
| 7 | API 路由与异常映射 | `api.py` |
| 8 | 单元测试（覆盖四大障碍类型） | `tests/profile/` |

## 十四、测试计划

- **类型层**：类型树加载、组合类型、非法类型。
- **属性层**：字段校验、必填项、非法取值、缺省推导。
- **框架引擎**：四大障碍类型 × 三种程度，断言生成的维度/指标/权重正确；`severe` 时指标细粒度与等级数符合预期。
- **接口**：创建/查询/更新/删除/预览/评分标准全链路，错误码正确。
- **持久化**：并发写加锁不丢数据、重启后可读取、索引与分片一致。

## 十五、风险与对策

| 风险 | 对策 |
|---|---|
| 维度/指标定义与特教专家意见不一致 | 全部走配置，专家可复核；预留维度与指标扩展 |
| 评价框架过重、教师负担大 | 按程度裁剪指标数量与等级；支持观测频率可调 |
| 程度叠加规则复杂难维护 | 规则显式化、可追溯，编写规则命中日志 |
| 下游误用不完整画像 | 提供校验接口，缺关键字段时返回明确错误 |
| 配置被随意改动 | 配置纳入版本管理，重载保留历史快照 |

## 十六、完成定义（DoD）

- 类型层、属性层、评价框架层、生成引擎、存储、API、测试全部完成。
- 四大障碍类型的评价框架生成结果经特教教师抽样确认。
- 通过 ruff 检查与 pytest 全绿。
- 学生实例与评价框架结构与下游模块（forge、loop）达成一致并冻结为契约。
