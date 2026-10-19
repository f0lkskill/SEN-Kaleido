"""类型层测试：加载障碍类型体系与未知类型报错。"""

import pytest

from kaleido.common.errors import ValidationError
from kaleido.profile.taxonomy import Taxonomy


def test_load_and_get():
    taxonomy = Taxonomy.load()
    visual = taxonomy.get("visual")
    assert visual.name == "视力障碍"
    assert "sensory" in visual.tags
    assert visual.defaults["sensory_preference"] == "audio_first"
    assert visual.prompt_template == "visual_layer"


def test_all_types():
    taxonomy = Taxonomy.load()
    assert set(taxonomy.keys()) == {"visual", "hearing", "intellectual", "autism"}


def test_unknown_type_raises():
    taxonomy = Taxonomy.load()
    with pytest.raises(ValidationError):
        taxonomy.get("unknown")
