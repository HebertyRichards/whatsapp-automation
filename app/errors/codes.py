from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class ErrorSpec:
    code: str
    http_status: int
    message: str


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"

    EVOLUTION_REJECTED = "EVOLUTION_REJECTED"
    EVOLUTION_UNAVAILABLE = "EVOLUTION_UNAVAILABLE"

    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"


ERROR_CATALOG: dict[ErrorCode, ErrorSpec] = {
    ErrorCode.VALIDATION_ERROR: ErrorSpec("VALIDATION_ERROR", 400, "Invalid data."),
    ErrorCode.UNAUTHENTICATED: ErrorSpec("UNAUTHENTICATED", 401, "Missing or invalid webhook secret."),
    ErrorCode.PAYLOAD_TOO_LARGE: ErrorSpec("PAYLOAD_TOO_LARGE", 400, "Request body too large; set base64 to false on the webhook."),

    ErrorCode.EVOLUTION_REJECTED: ErrorSpec("EVOLUTION_REJECTED", 502, "The Evolution API rejected the request."),
    ErrorCode.EVOLUTION_UNAVAILABLE: ErrorSpec("EVOLUTION_UNAVAILABLE", 503, "The Evolution API is unavailable."),

    ErrorCode.INTERNAL_SERVER_ERROR: ErrorSpec("INTERNAL_SERVER_ERROR", 500, "Internal server error."),
}
