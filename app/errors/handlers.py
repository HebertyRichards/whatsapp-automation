import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config.settings import get_settings
from app.errors.codes import ERROR_CATALOG, ErrorCode
from app.errors.exceptions import AppException

logger = logging.getLogger(__name__)


def _payload(code: ErrorCode, message: str, details: dict[str, object] | None = None) -> dict[str, object]:
    error: dict[str, object] = {"code": code.value, "message": message}
    if details:
        error["details"] = details
    return {"error": error}


async def app_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppException):
        raise exc
    if exc.http_status >= 500:
        logger.error("[%s] %s path=%s", exc.code.value, exc.message, request.url.path)
    return JSONResponse(
        status_code=exc.http_status,
        content=_payload(exc.code, exc.message, exc.details),
    )


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    details: dict[str, object] | None = None if get_settings().is_production else {"errors": exc.errors()}
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=_payload(
            ErrorCode.VALIDATION_ERROR,
            ERROR_CATALOG[ErrorCode.VALIDATION_ERROR].message,
            details,
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s", request.url.path)
    spec = ERROR_CATALOG[ErrorCode.INTERNAL_SERVER_ERROR]
    return JSONResponse(
        status_code=spec.http_status,
        content=_payload(ErrorCode.INTERNAL_SERVER_ERROR, spec.message),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
