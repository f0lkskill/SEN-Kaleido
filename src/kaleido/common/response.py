"""统一 API 响应结构。

所有接口返回统一包裹，便于教室机前端用一种方式解析：
成功 ``{code:0, message:"ok", data:{...}}``；
失败 ``{code:非0, message:"错误说明", data:null}``。
"""

from typing import Any


def ok(data: Any = None, message: str = "ok") -> dict:
    """构造成功响应体。"""
    return {"code": 0, "message": message, "data": data}


def fail(code: int, message: str) -> dict:
    """构造失败响应体。"""
    return {"code": code, "message": message, "data": None}
