"""统一服务集成测试：静态前端 + 三模块 API 合并 + 异步任务打通 forge。"""

import sys
from pathlib import Path

# 直接运行本测试文件时，把项目根与 src 加入模块搜索路径，保证无需安装即可执行
ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import json
import sys
import time
from io import BytesIO

from kaleido.api.app import create_app
from kaleido.profile.repository import StudentRepository
from kaleido.profile.service import ProfileService
from kaleido.vault import Vault


def _call(app, method, path, body=None, query=""):
    """调用 WSGI 应用，返回 (状态行, 内容类型, 原始字节)。"""
    payload = b""
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
    environ = {
        "REQUEST_METHOD": method,
        "SCRIPT_NAME": "",
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(payload)),
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": BytesIO(payload),
        "wsgi.errors": sys.stderr,
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = dict(headers)

    chunks = app(environ, start_response)
    raw = b"".join(chunks)
    if hasattr(chunks, "close"):
        chunks.close()
    return captured["status"], captured["headers"].get("Content-Type", ""), raw


def _json(raw):
    """解析 JSON 响应。"""
    return json.loads(raw.decode("utf-8")) if raw else {}


def _wait_task(app, task_id, timeout=5.0):
    """轮询任务直至进入终态。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, _, raw = _call(app, "GET", f"/api/v1/tasks/{task_id}")
        data = _json(raw)["data"]
        if data["status"] in ("succeeded", "failed", "cancelled"):
            return data
        time.sleep(0.05)
    raise AssertionError(f"任务未在 {timeout}s 内完成: {task_id}")


def _app(tmp_path):
    """构建使用临时数据目录的统一应用。"""
    vault = Vault(data_dir=tmp_path)
    profile_service = ProfileService(repository=StudentRepository(tmp_path))
    return create_app(vault=vault, profile_service=profile_service)


def test_serves_frontend_index(tmp_path):
    """根路径返回前端首页 HTML。"""
    app = _app(tmp_path)
    status, content_type, raw = _call(app, "GET", "/")
    assert status.startswith("200")
    assert "text/html" in content_type
    assert "SEN-Kaleido" in raw.decode("utf-8")


def test_serves_static_assets(tmp_path):
    """静态资源可访问，且 API 前缀不会被当作静态文件。"""
    app = _app(tmp_path)
    status, content_type, _ = _call(app, "GET", "/assets/css/tokens.css")
    assert status.startswith("200")
    assert "text/css" in content_type

    status, _, _ = _call(app, "GET", "/api/v1/does-not-exist")
    assert status.startswith("404")


def test_profile_route_available(tmp_path):
    """统一入口下 profile 建档接口可用。"""
    app = _app(tmp_path)
    body = {
        "name": "小测",
        "attributes": {
            "disabilities": ["visual"],
            "severity": "mild",
            "cognitive_level": "primary_3",
            "learning_pace": "medium",
        },
    }
    status, _, raw = _call(app, "POST", "/api/v1/students", body)
    assert status.startswith("201")
    assert _json(raw)["data"]["name"] == "小测"


def test_prompt_rules_route_available(tmp_path):
    """统一入口下规则集可列出并审核。"""
    vault = Vault(data_dir=tmp_path)
    profile_service = ProfileService(repository=StudentRepository(tmp_path))
    app = create_app(vault=vault, profile_service=profile_service)

    from kaleido.rules.service import PromptRuleService

    rule = PromptRuleService(vault=vault).add_rules(
        "visual", ["规则一"], source_topic="主题"
    )[0]
    status, _, raw = _call(app, "GET", "/api/v1/prompt-rules")
    assert status.startswith("200")
    assert _json(raw)["data"]["total"] == 1

    status, _, raw = _call(
        app,
        "PATCH",
        f"/api/v1/prompt-rules/{rule['rule_id']}",
        {"status": "approved"},
    )
    assert status.startswith("200")
    assert _json(raw)["data"]["status"] == "approved"


def test_forge_task_registered(tmp_path):
    """forge.generate 处理器已注册到任务队列。"""
    app = _app(tmp_path)
    status, _, raw = _call(app, "GET", "/api/v1/tasks/types")
    assert status.startswith("200")
    assert "forge.generate" in _json(raw)["data"]["task_types"]
    assert "forge.portrait" in _json(raw)["data"]["task_types"]
    assert "facet.evaluate" in _json(raw)["data"]["task_types"]


def test_facet_evaluate_via_unified_app(tmp_path, monkeypatch):
    """统一入口下可对资源执行质量校验。"""
    monkeypatch.setenv("SEN_KALEIDO_LLM_PROVIDER", "stub")
    app = _app(tmp_path)
    body = {
        "attributes": {
            "disabilities": ["visual"],
            "severity": "mild",
            "cognitive_level": "primary_3",
            "sensory_preference": "visual_first",
            "learning_pace": "medium",
        },
        "resource_type": "courseware",
        "topic": "认识四季",
    }
    status, _, raw = _call(app, "POST", "/api/v1/forge/generate", body, query="sync=1")
    assert status.startswith("201")
    resource_id = _json(raw)["data"]["resource_id"]

    status, _, raw = _call(
        app, "POST", f"/api/v1/facet/resources/{resource_id}/evaluate", {}
    )
    assert status.startswith("202")
    task_id = _json(raw)["data"]["task_id"]
    task = _wait_task(app, task_id)
    assert task["status"] == "succeeded"
    assert task["result"]["resource_id"] == resource_id
    assert task["stream_content"], "质检任务的流式输出应写入任务记录"

    status, _, raw = _call(app, "GET", f"/api/v1/facet/resources/{resource_id}")
    assert status.startswith("200")
    data = _json(raw)["data"]
    assert data["resource_id"] == resource_id
    assert data["verdict"] in ("pass", "review", "fail")

    items = _task_items(app, "facet.evaluate")
    assert len(items) == 1
    assert items[0]["result"]["verdict"] == data["verdict"]


def test_forge_generate_via_task(tmp_path, monkeypatch):
    """通过异步任务执行 forge 生成（使用桩客户端，离线）。"""
    # 强制使用离线桩，避免测试联网
    monkeypatch.setenv("SEN_KALEIDO_LLM_PROVIDER", "stub")
    app = _app(tmp_path)

    payload = {
        "task_type": "forge.generate",
        "payload": {
            "attributes": {
                "disabilities": ["hearing"],
                "severity": "moderate",
                "cognitive_level": "primary_5",
                "learning_pace": "slow",
            },
            "resource_type": "exercise",
            "topic": "看图识字",
        },
        "max_attempts": 1,
    }
    status, _, raw = _call(app, "POST", "/api/v1/tasks", payload)
    assert status.startswith("201")
    task_id = _json(raw)["data"]["task_id"]

    # 轮询任务直至完成
    result = None
    for _ in range(60):
        _, _, raw = _call(app, "GET", f"/api/v1/tasks/{task_id}")
        data = _json(raw)["data"]
        if data["status"] in ("succeeded", "failed"):
            result = data
            break
        time.sleep(0.05)

    assert result is not None, "任务未在超时内完成"
    assert result["status"] == "succeeded"
    assert result["result"]["resource_id"].startswith("r_")


def _task_items(app, task_type="forge.generate"):
    """读取指定类型的任务列表。"""
    _, _, raw = _call(
        app, "GET", "/api/v1/tasks", query=f"task_type={task_type}&size=50"
    )
    return _json(raw)["data"]["items"]


def test_forge_generate_queues_task(tmp_path, monkeypatch):
    """普通生成接口默认入队，不占用请求线程。"""
    monkeypatch.setenv("SEN_KALEIDO_LLM_PROVIDER", "stub")
    app = _app(tmp_path)
    body = {
        "attributes": {
            "disabilities": ["visual"],
            "severity": "mild",
            "cognitive_level": "primary_3",
            "learning_pace": "medium",
        },
        "resource_type": "courseware",
        "topic": "认识四季",
    }
    status, _, raw = _call(app, "POST", "/api/v1/forge/generate", body)
    assert status.startswith("202")
    queued = _json(raw)["data"]
    assert queued["status"] == "pending"

    task = _wait_task(app, queued["task_id"])
    assert task["status"] == "succeeded"
    assert task["task_type"] == "forge.generate"
    resource_id = task["result"]["resource_id"]
    assert resource_id.startswith("r_")
    assert task["stream_content"], "生成任务的流式输出应写入任务记录"

    status, _, raw = _call(app, "GET", f"/api/v1/forge/resources/{resource_id}")
    assert status.startswith("200")
    assert _json(raw)["data"]["content"]
    assert task["started_at"] and task["finished_at"]


def test_forge_generate_sync_mode(tmp_path, monkeypatch):
    """``?sync=1`` 保留同步生成行为，便于脚本与兼容调用。"""
    monkeypatch.setenv("SEN_KALEIDO_LLM_PROVIDER", "stub")
    app = _app(tmp_path)
    body = {
        "attributes": {
            "disabilities": ["hearing"],
            "severity": "moderate",
            "cognitive_level": "primary_5",
            "learning_pace": "slow",
        },
        "resource_type": "exercise",
        "topic": "看图识字",
    }
    status, _, raw = _call(app, "POST", "/api/v1/forge/generate", body, query="sync=1")
    assert status.startswith("201")
    resource_id = _json(raw)["data"]["resource_id"]
    assert _json(raw)["data"]["content"]

    items = _task_items(app)
    assert len(items) == 1
    assert items[0]["status"] == "succeeded"
    assert items[0]["result"]["resource_id"] == resource_id


def test_forge_stream_records_task(tmp_path, monkeypatch):
    """流式生成同样会在任务队列留下 succeeded 记录。"""
    monkeypatch.setenv("SEN_KALEIDO_LLM_PROVIDER", "stub")
    app = _app(tmp_path)
    body = {
        "attributes": {
            "disabilities": ["hearing"],
            "severity": "moderate",
            "cognitive_level": "primary_5",
            "learning_pace": "slow",
        },
        "resource_type": "exercise",
        "topic": "看图识字",
    }
    status, _, raw = _call(app, "POST", "/api/v1/forge/generate/stream", body)
    assert status.startswith("200")
    text = raw.decode("utf-8")
    assert '"type": "done"' in text
    resource_id = None
    for line in text.splitlines():
        if line.startswith("data: "):
            event = json.loads(line[6:])
            if event.get("type") == "done":
                resource_id = event["resource_id"]
    assert resource_id

    items = _task_items(app)
    assert len(items) == 1
    task = items[0]
    assert task["status"] == "succeeded"
    assert task["result"]["resource_id"] == resource_id


def test_evidence_verified_triggers_loop_task(tmp_path):
    """证据审核通过后自动投递 loop.evaluate 并生成评价快照。"""
    app = _app(tmp_path)
    status, _, raw = _call(
        app,
        "POST",
        "/api/v1/students",
        {
            "name": "小评",
            "attributes": {
                "disabilities": ["visual"],
                "severity": "moderate",
                "cognitive_level": "primary_3",
                "learning_pace": "medium",
            },
        },
    )
    assert status.startswith("201")
    student_id = _json(raw)["data"]["profile_id"]

    status, _, raw = _call(
        app,
        "POST",
        "/api/v1/evidence",
        {
            "student_id": student_id,
            "observation_key": "class_engagement",
            "source_type": "classroom_observation",
            "media_type": "text",
            "content": "课堂中主动举手两次。",
            "level": 4,
        },
    )
    assert status.startswith("201")
    evidence_id = _json(raw)["data"]["evidence_id"]

    status, _, raw = _call(
        app,
        "POST",
        f"/api/v1/evidence/{evidence_id}/review",
        {"status": "verified", "verified_by": "教师"},
    )
    assert status.startswith("200")

    task = None
    for _ in range(60):
        items = _task_items(app, "loop.evaluate")
        if items and items[0]["status"] in ("succeeded", "failed"):
            task = items[0]
            break
        time.sleep(0.05)
    assert task is not None, "自动触发的学情评价任务未完成"
    assert task["status"] == "succeeded"
    assert task["payload"]["trigger"] == "evidence_verified"

    status, _, raw = _call(
        app, "GET", f"/api/v1/loop/students/{student_id}/latest"
    )
    assert status.startswith("200")
    snapshot = _json(raw)["data"]
    assert snapshot["student_id"] == student_id
    assert snapshot["status"] == "partial"
    assert snapshot["dimension_scores"]["participation"] == 1.0


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
