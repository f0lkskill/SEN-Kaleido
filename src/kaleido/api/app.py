"""统一 API 服务入口：合并各模块路由并托管前端静态资源。

设计要点：
- 处理基站是唯一写入方，因此在同一进程内共享同一个 :class:`~kaleido.vault.Vault`，
  避免多集合实例各自持有文件锁；
- 通过 Bottle 的 ``merge`` 把 profile / forge / vault 三个子应用合并为一个服务；
- 末尾挂载静态前端（``src/web``），前端与后端脚本目录相互独立；
- 生产环境用 ``waitress`` 多线程 WSGI 承载多教室机并发访问。
"""

import os
from typing import Any, cast

from bottle import Bottle, abort, request, response, static_file

from kaleido.common.logging import get_logger, setup_logging
from kaleido.common.paths import DATA_DIR, WEB_DIR

logger = get_logger("api")
from kaleido.evidence.api import create_app as create_evidence_app
from kaleido.evidence.repository import EvidenceRepository
from kaleido.evidence.service import EvidenceService
from kaleido.forge.models import GenerateRequest
from kaleido.profile.api import create_app as create_profile_app
from kaleido.profile.repository import StudentRepository
from kaleido.profile.service import ProfileService
from kaleido.tasks.api import create_app as create_tasks_app
from kaleido.tasks.service import TaskService
from kaleido.vault import Vault
from kaleido.vault.api import create_app as create_vault_app

# forge 依赖可能未安装（例如纯画像部署），延迟导入以免整体不可用
try:  # pragma: no cover - 取决于部署形态
    from kaleido.forge.api import create_app as create_forge_app
    from kaleido.forge.service import ForgeService
except Exception:  # noqa: BLE001
    create_forge_app = None  # type: ignore[assignment]
    ForgeService = None  # type: ignore[assignment]


def create_app(vault: Vault | None = None, profile_service: ProfileService | None = None) -> Bottle:
    """构建合并后的应用：API 路由 + 静态前端。

    可选注入 ``vault`` / ``profile_service`` 便于测试使用临时数据目录。
    """
    # bottle 路由装饰器类型标注有缺陷，用 Any 视图规避误报
    app = cast(Any, Bottle())

    # 单一 Vault 实例在三层间共享，保证磁盘锁与索引一致
    vault = vault or Vault()
    profile_repository = StudentRepository(vault=vault)
    profile_service = profile_service or ProfileService(repository=profile_repository)
    app.merge(create_profile_app(profile_service))
    app.merge(create_vault_app(vault))

    # 证据管理：与学生档案共用同一 vault 与仓库，保证跨模块一致
    evidence_service = EvidenceService(
        repository=EvidenceRepository(vault=vault),
        student_repository=profile_repository,
    )
    app.merge(create_evidence_app(evidence_service))

    # 异步任务服务：注册 forge 生成处理器，供批量/闲时调度使用
    task_service = TaskService(vault=vault)
    if create_forge_app is not None and ForgeService is not None:
        forge_service = ForgeService(profile_service=profile_service, vault=vault)
        app.merge(create_forge_app(forge_service))
        task_service.register(
            "forge.generate",
            lambda payload: forge_service.generate(GenerateRequest(**payload)),
        )
    app.merge(create_tasks_app(task_service))

    # ---- 可选访问日志（默认关闭，设 SEN_KALEIDO_ACCESS_LOG=1 开启） ----
    if os.environ.get("SEN_KALEIDO_ACCESS_LOG") == "1":

        @app.hook("before_request")
        def _log_request() -> None:
            if request.path.startswith("/api/"):
                logger.debug("%s %s", request.method, request.path)

        @app.hook("after_request")
        def _log_response() -> None:
            if request.path.startswith("/api/"):
                logger.info("%s %s -> %s", request.method, request.path, response.status_code)

    # ---- 静态前端：与后端脚本分离，按 assets 分类组织 ----
    @app.get("/")
    def index():
        """返回前端首页。"""
        # HTML 不缓存，便于基站更新前端后刷新即生效
        response.set_header("Cache-Control", "no-cache")
        return static_file("index.html", root=str(WEB_DIR))

    @app.get("/favicon.ico")
    def favicon():
        """站点图标（缺省返回 204，避免 404 噪声）。"""
        response.status = 204
        return ""

    @app.get("/<filepath:path>")
    def assets(filepath: str):
        """托管 assets 下的静态资源；API 前缀不在此处理。"""
        # 未命中的 API 路径不应被当作静态文件，直接 404
        if filepath.startswith("api/"):
            abort(404, "Not Found")
        # 静态资源允许缓存，减少教室机重复拉取
        response.set_header("Cache-Control", "public, max-age=3600")
        return static_file(filepath, root=str(WEB_DIR))

    return app


def serve(host: str = "0.0.0.0", port: int = 8080) -> None:
    """用 waitress 启动整站服务（默认端口 8080）。"""
    from waitress import serve as waitress_serve

    setup_logging()
    logger.info("SEN-Kaleido 服务启动: http://%s:%s", host, port)
    logger.info("数据目录: %s", DATA_DIR)
    logger.info(
        "日志级别: %s；访问日志: %s（设 SEN_KALEIDO_ACCESS_LOG=1 开启）",
        os.environ.get("SEN_KALEIDO_LOG_LEVEL", "INFO"),
        os.environ.get("SEN_KALEIDO_ACCESS_LOG", "0"),
    )
    waitress_serve(create_app(), host=host, port=port)


if __name__ == "__main__":
    serve()
