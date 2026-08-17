"""Unified error codes, AppError, and FastAPI exception handlers (§7.4)."""

from __future__ import annotations

from enum import Enum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ErrorCode(str, Enum):
    DB_SOURCE_001 = "DB_SOURCE_001"
    DB_SOURCE_002 = "DB_SOURCE_002"
    FILE_001 = "FILE_001"
    FILE_002 = "FILE_002"
    FILE_003 = "FILE_003"
    FILE_004 = "FILE_004"
    SCHEMA_001 = "SCHEMA_001"
    SCHEMA_002 = "SCHEMA_002"
    SCHEMA_003 = "SCHEMA_003"
    SCHEMA_004 = "SCHEMA_004"
    SCHEMA_005 = "SCHEMA_005"
    MAPPING_001 = "MAPPING_001"
    MAPPING_002 = "MAPPING_002"
    TASK_001 = "TASK_001"
    TASK_002 = "TASK_002"
    GRAPH_001 = "GRAPH_001"
    BIZLOGIC_001 = "BIZLOGIC_001"
    LLM_001 = "LLM_001"
    LLM_002 = "LLM_002"
    LLM_003 = "LLM_003"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    VALIDATION_ERROR = "VALIDATION_ERROR"


DEFAULT_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.DB_SOURCE_001: "连接失败，请检查主机地址与端口",
    ErrorCode.DB_SOURCE_002: "该连接名称已存在，请更换",
    ErrorCode.FILE_001: "暂不支持该文件类型",
    ErrorCode.FILE_002: "单个文件不能超过 200MB",
    ErrorCode.FILE_003: "文件解析失败，请检查文件是否损坏",
    ErrorCode.FILE_004: "请先选择至少一个已解析完成的文档",
    ErrorCode.SCHEMA_001: "该类已存在，请更换名称",
    ErrorCode.SCHEMA_002: "该域下已存在同名属性，请更换名称",
    ErrorCode.SCHEMA_003: "TTL 文件解析失败，请检查语法",
    ErrorCode.SCHEMA_004: "该类下存在实例数据，请先清理实例后再删除",
    ErrorCode.SCHEMA_005: "目标 Schema 尚无任何类，请先完成 Schema 设计",
    ErrorCode.MAPPING_001: "请至少绑定一个字段作为实例 URI",
    ErrorCode.MAPPING_002: "字段类型与属性数据类型不匹配",
    ErrorCode.TASK_001: "抽取任务不存在",
    ErrorCode.TASK_002: "该任务正在执行，请勿重复触发",
    ErrorCode.GRAPH_001: "指定的 Schema 不存在",
    ErrorCode.BIZLOGIC_001: "请先完成本体实例抽取，再进行业务逻辑抽取",
    ErrorCode.LLM_001: "模型配置不存在",
    ErrorCode.LLM_002: "模型名称已存在，请更换",
    ErrorCode.LLM_003: "模型连通性测试失败，请检查 API 地址、密钥与模型名",
    ErrorCode.INTERNAL_ERROR: "服务器内部错误，请稍后重试",
    ErrorCode.NOT_FOUND: "资源不存在",
    ErrorCode.CONFLICT: "资源状态冲突",
    ErrorCode.VALIDATION_ERROR: "请求参数校验失败",
}

HTTP_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.DB_SOURCE_001: 400,
    ErrorCode.DB_SOURCE_002: 409,
    ErrorCode.FILE_001: 400,
    ErrorCode.FILE_002: 400,
    ErrorCode.FILE_003: 400,
    ErrorCode.FILE_004: 400,
    ErrorCode.SCHEMA_001: 409,
    ErrorCode.SCHEMA_002: 409,
    ErrorCode.SCHEMA_003: 400,
    ErrorCode.SCHEMA_004: 409,
    ErrorCode.SCHEMA_005: 400,
    ErrorCode.MAPPING_001: 400,
    ErrorCode.MAPPING_002: 400,
    ErrorCode.TASK_001: 404,
    ErrorCode.TASK_002: 409,
    ErrorCode.GRAPH_001: 404,
    ErrorCode.BIZLOGIC_001: 400,
    ErrorCode.LLM_001: 404,
    ErrorCode.LLM_002: 409,
    ErrorCode.LLM_003: 400,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.VALIDATION_ERROR: 400,
}


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        *,
        field: str | None = None,
        status_code: int | None = None,
        details: Any = None,
    ) -> None:
        self.code = code
        self.message = message or DEFAULT_MESSAGES.get(code, code.value)
        self.field = field
        self.status_code = status_code or HTTP_STATUS_BY_CODE.get(code, 400)
        self.details = details
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "error": {
                "code": self.code.value,
                "message": self.message,
                "field": self.field,
            }
        }
        return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        field = None
        message = DEFAULT_MESSAGES[ErrorCode.VALIDATION_ERROR]
        errors = exc.errors()
        if errors:
            loc = errors[0].get("loc") or ()
            # skip "body" / "query" prefix
            parts = [str(p) for p in loc if p not in ("body", "query", "path")]
            if parts:
                field = parts[-1]
            message = errors[0].get("msg", message)
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": ErrorCode.VALIDATION_ERROR.value,
                    "message": message,
                    "field": field,
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": ErrorCode.INTERNAL_ERROR.value,
                    "message": DEFAULT_MESSAGES[ErrorCode.INTERNAL_ERROR],
                    "field": None,
                }
            },
        )
