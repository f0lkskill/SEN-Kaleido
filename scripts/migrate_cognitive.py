"""数据迁移：把旧认知等级键迁移为年级键。

旧版枚举 ``primary_low / primary_high`` 已替换为按年级的键
（``primary_3 / primary_5``），本脚本扫描 data/students 下所有档案，
改写其 ``attributes.cognitive_level`` 并重建索引。

用法：``python scripts/migrate_cognitive.py``。
"""

import sys
from pathlib import Path

# 直接运行时把项目根与 src 加入模块搜索路径
ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from kaleido.vault import Vault

MAP = {"primary_low": "primary_3", "primary_high": "primary_5"}


def main() -> int:
    """执行迁移，返回进程退出码。"""
    vault = Vault()
    collection = vault.collection("students")
    changed = 0
    for doc_id in collection.store.list_ids():
        payload = collection.get(doc_id)
        if not isinstance(payload, dict):
            continue
        attributes = payload.get("attributes") or {}
        level = attributes.get("cognitive_level")
        if level in MAP:
            attributes["cognitive_level"] = MAP[level]
            collection.put(doc_id, payload)
            changed += 1
            print(f"迁移 {doc_id}: {level} -> {MAP[level]}")
    if changed:
        collection.reindex()
    print(f"完成，共迁移 {changed} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
