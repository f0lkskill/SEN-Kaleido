"""并发测试：多线程与多进程写入不丢数据、ID 不冲突。"""

import multiprocessing as mp
import threading

from kaleido.vault import Vault

THREADS = 8
PER_THREAD = 10
PROCESSES = 2
PER_PROCESS = 5


def test_threads_unique_ids(tmp_path):
    collection = Vault(data_dir=tmp_path).collection("docs")
    ids: list[str] = []
    lock = threading.Lock()

    def worker():
        local = []
        for _ in range(PER_THREAD):
            doc_id = collection.next_id()
            collection.put(doc_id, {"v": doc_id})
            local.append(doc_id)
        with lock:
            ids.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(ids) == THREADS * PER_THREAD
    assert len(set(ids)) == THREADS * PER_THREAD
    _, total = collection.list(size=1000)
    assert total == THREADS * PER_THREAD


def _process_worker(data_dir: str, count: int) -> None:
    """子进程：独立 Vault 实例写入若干文档。"""
    collection = Vault(data_dir=data_dir).collection("docs")
    for index in range(count):
        doc_id = collection.next_id()
        collection.put(doc_id, {"v": f"{doc_id}-{index}"})


def test_multiprocess_unique_ids(tmp_path):
    ctx = mp.get_context("spawn")
    processes = [
        ctx.Process(target=_process_worker, args=(str(tmp_path), PER_PROCESS))
        for _ in range(PROCESSES)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join()
    assert all(process.exitcode == 0 for process in processes)

    collection = Vault(data_dir=tmp_path).collection("docs")
    collection.reindex()
    _, total = collection.list(size=1000)
    assert total == PROCESSES * PER_PROCESS
