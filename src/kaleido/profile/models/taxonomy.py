"""类型层数据模型：学生障碍类型（分类体系）。

类型不是孤立枚举，而是带父类型与标签的节点，支持组合表达"多重障碍"，
后续新增类型只需扩展配置文件。
"""

from pydantic import BaseModel, Field


class StudentType(BaseModel):
    """一种障碍类型定义。"""

    key: str  # 类型唯一键，如 visual / hearing / intellectual / autism
    name: str  # 中文名称，如"视力障碍"
    parent: str | None = None  # 父类型键，用于构建分类树
    tags: list[str] = Field(default_factory=list)  # 分类标签，如 sensory / cognitive
    defaults: dict = Field(default_factory=dict)  # 该类型的默认属性（如默认感官偏好）
    constraints: dict = Field(default_factory=dict)  # 该类型的适配约束，传给生成层
    prompt_template: str = ""  # 关联的生成层 Prompt 模板键
