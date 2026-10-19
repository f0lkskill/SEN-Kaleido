"""恢复性测试：索引损坏/丢失后的重建与一致性。"""

import sys
from pathlib import Path

# 直接运行本测试文件时，把项目根与 src 加入模块搜索路径，保证无需安装即可执行
ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from kaleido.vault import Vault


def test_reindex_after_index_loss(tmp_path):
    vault = Vault(data_dir=tmp_path)
    collection = vault.collection("students")
    collection.put(
        "p_0001",
        {
            "name": "小明",
            "attributes": {
                "disabilities": ["visual"],
                "severity": "mild",
                "cognitive_level": "primary_3",
            },
        },
    )
    collection.index_path.unlink()

    reopened = Vault(data_dir=tmp_path).collection("students")
    reopened.reindex()
    items, total = reopened.list({"attributes.disabilities": "visual"})
    assert total == 1
    assert items[0]["name"] == "小明"


def test_corrupt_index_falls_back_to_empty(tmp_path):
    vault = Vault(data_dir=tmp_path)
    collection = vault.collection("docs")
    collection.put("d_0001", {"a": 1})

    collection.index_path.write_text("{broken", encoding="utf-8")
    reopened = Vault(data_dir=tmp_path).collection("docs")
    # 索引损坏时回退为空索引，但重建后恢复
    reopened.reindex()
    _, total = reopened.list()
    assert total == 1


def test_counter_preserved_across_instances(tmp_path):
    first = Vault(data_dir=tmp_path).collection("docs")
    assert first.next_id() == "d_0001"
    second = Vault(data_dir=tmp_path).collection("docs")
    assert second.next_id() == "d_0002"

if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
