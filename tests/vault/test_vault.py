"""注册中心测试：配置驱动的集合规格与命名空间。"""

import sys
from pathlib import Path

# 直接运行本测试文件时，把项目根与 src 加入模块搜索路径，保证无需安装即可执行
ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from kaleido.vault import Vault


def test_namespaces(tmp_path):
    vault = Vault(data_dir=tmp_path)
    assert "students" in vault.namespaces()


def test_students_spec_from_config(tmp_path):
    collection = Vault(data_dir=tmp_path).collection("students")
    assert collection.spec.envelope is False
    assert collection.spec.idempotent is True
    assert collection.spec.id_prefix == "p"
    assert "attributes.disabilities" in collection.spec.index_fields


def test_unknown_namespace_defaults(tmp_path):
    collection = Vault(data_dir=tmp_path).collection("misc")
    assert collection.spec.name == "misc"
    assert collection.spec.envelope is True
    assert collection.root.name == "misc"


def test_collection_cached(tmp_path):
    vault = Vault(data_dir=tmp_path)
    assert vault.collection("students") is vault.collection("students")

if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
