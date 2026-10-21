"""属性层测试：默认值推导、显式覆盖与非法取值校验。"""

import sys
from pathlib import Path

# 直接运行本测试文件时，把项目根与 src 加入模块搜索路径，保证无需安装即可执行
ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest

from kaleido.common.errors import ValidationError
from kaleido.profile.attributes import AttributeSchema
from kaleido.profile.models.student import StudentAttributesInput
from kaleido.profile.taxonomy import Taxonomy


def _schema() -> AttributeSchema:
    return AttributeSchema.load()


def test_resolve_defaults_sensory():
    schema = _schema()
    taxonomy = Taxonomy.load()
    resolved = schema.resolve(
        taxonomy,
        StudentAttributesInput(
            disabilities=["visual"],
            severity="moderate",
            cognitive_level="primary_3",
            learning_pace="slow",
        ),
    )
    assert resolved.sensory_preference == "audio_first"
    assert resolved.adaptation_constraints["format"] == "voice_first"
    assert resolved.prompt_template_key == "visual_layer"


def test_explicit_sensory_overrides_default():
    schema = _schema()
    taxonomy = Taxonomy.load()
    resolved = schema.resolve(
        taxonomy,
        StudentAttributesInput(
            disabilities=["visual"],
            severity="moderate",
            cognitive_level="primary_3",
            sensory_preference="mixed",
            learning_pace="slow",
        ),
    )
    assert resolved.sensory_preference == "mixed"


def test_invalid_enum_raises():
    schema = _schema()
    taxonomy = Taxonomy.load()
    with pytest.raises(ValidationError):
        schema.resolve(
            taxonomy,
            StudentAttributesInput(
                disabilities=["visual"],
                severity="unknown",
                cognitive_level="primary_3",
                learning_pace="slow",
            ),
        )


def test_invalid_rehab_goal_raises():
    schema = _schema()
    taxonomy = Taxonomy.load()
    with pytest.raises(ValidationError):
        schema.resolve(
            taxonomy,
            StudentAttributesInput(
                disabilities=["visual"],
                severity="mild",
                cognitive_level="primary_3",
                rehab_goals=["dance"],
                learning_pace="slow",
            ),
        )

def test_avoid_visual_ref_disables_emoji():
    schema = _schema()
    taxonomy = Taxonomy.load()
    resolved = schema.resolve(
        taxonomy,
        StudentAttributesInput(
            disabilities=["visual", "intellectual"],
            severity="moderate",
            cognitive_level="primary_3",
            learning_pace="slow",
        ),
    )
    constraints = resolved.adaptation_constraints
    assert constraints["avoid_visual_ref"] is True
    assert constraints["add_emoji"] is False
    assert constraints["step_by_step"] is True


def _constraints(schema, taxonomy, disabilities):
    """解析给定障碍组合的适配约束。"""
    resolved = schema.resolve(
        taxonomy,
        StudentAttributesInput(
            disabilities=disabilities,
            severity="moderate",
            cognitive_level="primary_3",
            learning_pace="slow",
        ),
    )
    return resolved.adaptation_constraints


def test_multi_disability_constraints_ignore_order():
    """安全约束不因障碍书写顺序而被覆盖。"""
    schema = _schema()
    taxonomy = Taxonomy.load()
    for disabilities in (["visual", "autism"], ["autism", "visual"]):
        constraints = _constraints(schema, taxonomy, disabilities)
        assert constraints["avoid_visual_ref"] is True
        assert constraints["add_emoji"] is False
        assert constraints["visual_aid"] is False
        assert constraints["simple_vocab"] is True
        assert constraints["short_sentence"] is True


def test_multi_disability_numeric_constraint_takes_strictest():
    """数值型约束取最严格值，与障碍顺序无关。"""
    schema = _schema()
    taxonomy = Taxonomy.load()
    for disabilities in (
        ["visual", "intellectual"],
        ["intellectual", "visual"],
    ):
        constraints = _constraints(schema, taxonomy, disabilities)
        assert constraints["sentence_length_max"] == 12
        assert constraints["step_by_step"] is True


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
