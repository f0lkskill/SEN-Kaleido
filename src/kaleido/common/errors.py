"""SEN-Kaleido 统一异常定义。

所有业务异常继承 :class:`KaleidoError`，携带业务错误码 ``code`` 与
HTTP 状态码 ``http_status``，由 API 层统一捕获并映射为统一响应结构，
避免在业务代码中到处散落状态码。
"""


class KaleidoError(Exception):
    """业务异常基类，代表未分类的未知错误。"""

    code = 1000
    http_status = 500

    def __init__(self, message: str):
        super().__init__(message)
        # 便于 API 层直接读取错误信息
        self.message = message


class ValidationError(KaleidoError):
    """参数或数据校验失败（HTTP 400）。"""

    code = 1001
    http_status = 400


class NotFoundError(KaleidoError):
    """资源不存在（HTTP 404）。"""

    code = 1002
    http_status = 404


class ConflictError(KaleidoError):
    """资源冲突，例如幂等请求 ID 重复（HTTP 409）。"""

    code = 1003
    http_status = 409


class ConfigError(KaleidoError):
    """配置文件缺失或内容非法（HTTP 500）。"""

    code = 1004
    http_status = 500


class StorageError(KaleidoError):
    """本地存储读写失败（HTTP 500）。"""

    code = 1005
    http_status = 500
