"""集合测试：ID、CRUD、幂等、索引筛选、分页与重建索引。"""

import pytest

from kaleido.common.errors import NotFoundError
from kaleido.vault.collection import Collection
from kaleido.vault.models import CollectionSpec


def _collection(tmp_path, **overrides) -> Collection:
    spec_kwargs = {
        "name": "docs",
        "id_prefix": "d",
        "id_zerofill": 3,
        "envelope": False,
        "idempotent": True,
        "index_fields": ["kind", "nest.tag"],
    }
    spec_kwargs.update(overrides)
    return Collection(CollectionSpec(**spec_kwargs), tmp_path)


def _doc(kind: str = "a", tag: str = "x") -> dict:
    return {"kind": kind, "nest": {"tag": tag}}


def test_next_id_format(tmp_path):
    collection = _collection(tmp_path)
    assert collection.next_id() == "d_001"
    assert collection.next_id() == "d_002"


def test_put_get_delete(tmp_path):
    collection = _collection(tmp_path)
    collection.put("d_001", _doc())
    assert collection.get("d_001") == _doc()
    collection.delete("d_001")
    with pytest.raises(NotFoundError):
        collection.get("d_001")


def test_idempotency_key(tmp_path):
    collection = _collection(tmp_path)
    collection.put("d_001", _doc(), idempotency_key="req-1")
    assert collection.find_by_key("req-1") == "d_001"
    assert collection.find_by_key("missing") is None
    assert collection.find_by_key(None) is None


def test_list_filters_and_paging(tmp_path):
    collection = _collection(tmp_path)
    for i in range(5):
        collection.put(f"d_{i:03d}", _doc(kind="a" if i % 2 == 0 else "b"))
    items, total = collection.list({"kind": "a"}, page=1, size=10)
    assert total == 3
    assert all(item["kind"] == "a" for item in items)

    page1, total = collection.list(page=1, size=2)
    page2, _ = collection.list(page=2, size=2)
    assert len(page1) == 2 and len(page2) == 2
    assert {item["id"] for item in page1}.isdisjoint({item["id"] for item in page2})


def test_point_path_index(tmp_path):
    collection = _collection(tmp_path)
    collection.put("d_001", _doc(tag="special"))
    items, total = collection.list({"nest.tag": "special"})
    assert total == 1
    assert items[0]["nest.tag"] == "special"


def test_envelope_mode(tmp_path):
    collection = _collection(tmp_path, envelope=True)
    collection.put("d_001", _doc())
    raw = collection.store.read("d_001")
    assert raw["id"] == "d_001"
    assert "created_at" in raw and "updated_at" in raw
    assert raw["payload"] == _doc()
    # get 自动解包为业务内容
    assert collection.get("d_001") == _doc()


def test_reindex_rebuilds_entries(tmp_path):
    collection = _collection(tmp_path)
    collection.put("d_001", _doc(kind="a"))
    collection.index_path.unlink()
    collection.reindex()
    items, total = collection.list({"kind": "a"})
    assert total == 1
    assert items[0]["id"] == "d_001"
