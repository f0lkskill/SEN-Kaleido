"""底层 JSON 存储测试：原子写、安全读、删除与文件枚举。"""

import pytest

from kaleido.common.errors import NotFoundError, StorageError
from kaleido.vault.jsonstore import JsonStore


def test_write_read_delete(tmp_path):
    store = JsonStore(tmp_path / "c")
    store.write_atomic("a", {"x": 1})
    assert store.exists("a")
    assert store.read("a") == {"x": 1}
    store.delete("a")
    assert not store.exists("a")


def test_read_missing(tmp_path):
    store = JsonStore(tmp_path / "c")
    with pytest.raises(NotFoundError):
        store.read("nope")


def test_corrupt_file_isolated(tmp_path):
    store = JsonStore(tmp_path / "c")
    (tmp_path / "c" / "bad.json").write_text("{oops", encoding="utf-8")
    with pytest.raises(StorageError):
        store.read("bad")


def test_list_ids_excludes_index_and_tmp(tmp_path):
    store = JsonStore(tmp_path / "c")
    store.write_atomic("a", {})
    store.write_path_atomic(store.root / "index.json", {})
    (store.root / "x.json.tmp").write_text("{}", encoding="utf-8")
    assert store.list_ids() == ["a"]
