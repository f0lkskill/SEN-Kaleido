# kaleido-forge 模块开发规划

> 版本 v1.0 ｜ 定位：多模态生成层
> 上游：`kaleido-profile`（学生画像）、`kaleido-tasks`（异步调度）
> 下游：`kaleido-facet`（质检）、`kaleido-vault`（资源落库）

## 一、模块概述

`kaleido-forge` 负责把**学生画像 + 教学主题 + 资源类型**转换为分层 Prompt，
调用云端大模型（`deepseek-flash`）生成特教资源，并写入 `kaleido-vault` 的
`resources` 集合（初始状态 `draft`，等待教师确认）。

### 1.1 职责边界

| 做 | 不做 |
|---|---|
| 分层 Prompt 拼装与模板管理 | 学生属性校验（归 profile） |
| 云端模型调用（OpenAI 兼容） | 质量评分（归 facet） |
| 生成结果结构化与落库 | 异步排队与闲时调度（归 tasks） |
| 资源列表/详情查询 | 内容安全与密钥下发（归 guard） |

设计原则：**不训练模型，靠工程化解决适配**；模型客户端可注入，测试全程离线。

## 二、架构与数据流

```
GenerateRequest
   │  profile_id / attributes
   ▼
ProfileService ──► 规范化属性（含 constraints / prompt_template_key）
   │
   ▼
PromptLoader（prompts/<template_key>.txt）
   │
   ▼
LLMClient（DeepSeekClient / StubClient）
   │
   ▼
GeneratedResource ──► vault.resources（status=draft）
```

## 三、目录结构

```
src/kaleido/forge/
├── __init__.py
├── models.py        GenerateRequest / GeneratedResource
├── llm_client.py    LLMClient 协议、DeepSeekClient、StubClient、create_client
├── prompts.py       模板加载（带缓存）与安全渲染
├── service.py       ForgeService：解析属性 → 拼 Prompt → 调用 → 落库
└── api.py           Bottle 路由
configs/forge/forge.yaml
prompts/
├── visual_layer.txt
├── hearing_layer.txt
├── intellectual_layer.txt
└── autism_layer.txt
tests/forge/
```

## 四、配置

`configs/forge/forge.yaml`：

```yaml
llm:
  provider: deepseek            # deepseek | stub
  base_url: https://api.deepseek.com
  model: deepseek-flash
  temperature: 0.7
  max_tokens: null              # 不设硬上限，使用 API 思考模式默认额度
  timeout: 60
  retries: 2
  api_key_env: DEEPSEEK_API_KEY
resource_types:
  courseware: 分层知识点课件
  exercise: 个性化练习题库
  rehabilitation: 多模态康复素材
  interaction: 课堂互动辅助资源
  iep: 个别化教学方案
```

密钥只从环境变量读取，**不下发客户端、不写入仓库**。

## 五、分层 Prompt

- 模板位于 `prompts/`，按 `prompt_template_key` 选择（来自 profile 类型层）。
- 占位符：`severity / cognitive_level / sensory_preference / learning_pace /
  constraints / resource_type / topic / extra`。
- 渲染缺失字段为空串，避免个别属性缺省导致失败。
- 硬性约束（如 `voice_first`、`require_caption`、`step_by_step`）由 profile
  属性层产出并注入，保证「画像 → 生成」口径一致。

## 六、模型客户端

- `LLMClient`：协议，`complete(messages, **overrides) -> LLMResult`。
- `DeepSeekClient`：`requests` 直调 `/chat/completions`，支持超时与重试，
  失败抛 `UpstreamError`（错误码 1006 / HTTP 502）。
- `StubClient`：离线桩，返回固定内容并记录调用，供单元测试与本地联调。
- `stream_complete(client, messages, on_event, **overrides)`：统一流式封装。
  真实客户端走 `stream`，逐块转发 `reasoning` / `content`；不支持流式的
  客户端自动回退 `complete`。资源生成、画像分析与质量评分均走此入口。
- `create_client(config)`：按 `provider` 选择实现。

## 七、接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/forge/generate` | 生成资源（`profile_id` 或 `attributes` 二选一）；默认入队返回 202，`?sync=1` 同步返回 |
| GET | `/api/v1/forge/resources` | 分页/筛选资源（`resource_type / disability / status`） |
| GET | `/api/v1/forge/resources/<id>` | 资源详情 |
| GET | `/api/v1/forge/resource-types` | 可用资源类型 |

请求示例：

```json
{
  "profile_id": "p_0001",
  "resource_type": "courseware",
  "topic": "认识四季",
  "extra": {"duration_minutes": 20}
}
```

## 八、与 profile / vault 的对接

- **profile**：`profile_id` 走 `ProfileService.get_student`；临时属性走
  `preview_framework` 取得规范化结果（含 `adaptation_constraints`）。
- **vault**：生成结果写入 `resources` 集合（`envelope=true`，索引字段
  `resource_type / disability / status`），便于 match 层检索。

## 九、测试

| 文件 | 覆盖点 |
|---|---|
| `test_llm_client.py` | 桩调用、配置工厂、缺密钥、请求构造、重试与错误映射 |
| `test_prompts.py` | 四类模板渲染、约束注入、缺失占位、缺失模板 |
| `test_service.py` | 画像/属性两种来源、Prompt 拼装、落库、筛选 |
| `test_api.py` | 生成、详情、列表、非法请求、资源类型 |

全部离线（`StubClient`），不依赖真实 API Key。

## 十、完成定义（DoD）

- 客户端、Prompt、服务、API、配置、模板全部实现。
- 生成结果可正确落库并按类型/障碍/状态检索。
- `pytest` 全绿，`pyright` 0 error。

## 十一、实现状态（已落地）

- **代码**：`src/kaleido/forge/{models,llm_client,prompts,service,api}.py`。
- **配置**：`configs/forge/forge.yaml`。
- **模板**：`prompts/{visual,hearing,intellectual,autism}_layer.txt`。
- **依赖**：新增 `requests`。
- **测试**：`tests/forge/`（llm_client / prompts / service / api）。
- **结果**：`pytest` 91 项全绿，`pyright` 0 error。
