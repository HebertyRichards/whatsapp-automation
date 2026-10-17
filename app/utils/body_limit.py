import logging

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.errors import ERROR_CATALOG, ErrorCode

logger = logging.getLogger(__name__)

# A text message webhook is a few KB. Anything near this is media sent as base64 or a history dump.
MAX_BODY_BYTES = 1_000_000


class BodyLimit:
    """Rejects a request whose declared size is over `max_bytes` before any of its body is read."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            length = dict(scope["headers"]).get(b"content-length", b"")
            if length.isdigit() and int(length) > self.max_bytes:
                logger.warning("Rejected a %s-byte request to %s", length.decode(), scope["path"])
                spec = ERROR_CATALOG[ErrorCode.PAYLOAD_TOO_LARGE]
                body = {"error": {"code": spec.code, "message": spec.message}}
                await JSONResponse(status_code=spec.http_status, content=body)(scope, receive, send)
                return
        await self.app(scope, receive, send)
