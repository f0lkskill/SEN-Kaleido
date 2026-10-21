# kaleido-rules 模块

> 定位：病症通用提示词规则集
> 上游：`kaleido-facet`（资源质检沉淀）
> 下游：`kaleido-forge`（生成时注入已审核规则）

## 一、职责

`kaleido-rules` 按**病症**归档模型从资源质检中提炼的共性问题：

- 模型新沉淀的规则进入 `pending`，等待教师审核；
- 教师可通过（`approved`）、拒绝（`rejected`）或删除；
- 只有 `approved` 规则会参与同类病症的资源生成；
- 规则集记录来源资源、主题、评分、来源学生与模型，便于追溯。

学生个体差异**不进入规则集**，而是写入该学生画像的
`personal_prompts`，仅在生成该学生资源时作为个性强化提示使用。

## 二、共性问题与个性问题

资源质检模板要求模型严格区分：

| 分类 | 判断标准 | 去向 |
|---|---|---|
| 共性问题 | 由障碍类型、程度、认知/感官/教学通用原则导致，同类病症学生普遍适用 | `prompt_rules`（按 `disability`） |
| 个性问题 | 仅因该学生的独特经验、感官敏感或学习习惯导致，无法泛化 | `profile.portrait.personal_prompts` |

同一个问题只能出现在一个分类中。个性提示不得包含学生姓名、个人经历或隐私。

## 三、数据模型

集合：`prompt_rules`（`envelope=true`，索引 `disability / status`）。

| 字段 | 说明 |
|---|---|
| `rule_id` | `pr_<hash>`，按病症与归一化文本生成，天然去重 |
| `disability` | 病症键：`visual / hearing / intellectual / autism` |
| `text` | 规则正文 |
| `status` | `pending / approved / rejected` |
| `source_resource_id` | 来源资源 |
| `source_topic` | 来源资源主题 |
| `source_score` | 来源资源综合评分 |
| `source_profile_id` | 来源学生（仅追溯） |
| `model` | 沉淀规则的模型 |
| `created_at / updated_at` | 时间戳 |

## 四、服务

`PromptRuleService`：

- `add_rules(disability, prompts, source...)`：写入并去重；
- `list_rules(disability?, status?)`：列出全部模型记录；
- `set_status(rule_id, status)`：通过/拒绝；
- `delete_rule(rule_id)`：物理删除；
- `approved_for(disabilities)`：生成时按学生病症顺序取已审核规则，
  每病症最多 `max_rules_per_disability` 条。

## 五、API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/prompt-rules` | 列表，支持 `disability` / `status` 筛选 |
| PATCH | `/api/v1/prompt-rules/<rule_id>` | `{"status": "approved"\|"rejected"}` |
| DELETE | `/api/v1/prompt-rules/<rule_id>` | 删除规则 |

## 六、配置

`configs/rules/rules.yaml`：

```yaml
max_rules_per_disability: 12   # 生成时每个病症最多注入的已审核规则数
max_chars_per_rule: 240        # 单条规则最大字符数
```

## 七、前端

“规则集”标签页按病症分组展示所有模型记录的规则：

- 顶部统计待审核/已通过/已拒绝数量；
- 支持按状态、病症筛选；
- 每条规则提供通过、拒绝、删除操作；
- 通过后无需重新生成资源，下一次生成自动生效。

学生档案不再展示个人提示词规则板；画像中新增“个性强化提示”分区。

## 八、测试

`tests/rules/` 覆盖沉淀、去重、审核、删除、生成取用与 API 流程；
`tests/facet/` 验证共性问题进入规则集、个性问题写入画像；
`tests/forge/` 验证只有已审核规则参与生成。
