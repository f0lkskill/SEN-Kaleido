"""属性层测试：默认值推导、显式覆盖与非法取值校验。"""

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
            disability="visual",
            severity="moderate",
            cognitive_level="primary_low",
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
            disability="visual",
            severity="moderate",
            cognitive_level="primary_low",
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
                disability="visual",
                severity="unknown",
                cognitive_level="primary_low",
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
                disability="visual",
                severity="mild",
                cognitive_level="primary_low",
                rehab_goals=["dance"],
                learning_pace="slow",
            ),
        )
