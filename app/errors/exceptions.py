from app.errors.codes import ERROR_CATALOG, ErrorCode


class AppException(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        spec = ERROR_CATALOG[code]
        self.code = code
        self.http_status = spec.http_status
        self.message = message or spec.message
        self.details: dict[str, object] = details or {}
        super().__init__(self.message)
