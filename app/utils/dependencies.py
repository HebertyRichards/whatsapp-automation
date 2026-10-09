import hmac

from fastapi import Header

from app.config.settings import get_settings
from app.errors import AppException, ErrorCode


async def verify_webhook_secret(x_webhook_secret: str = Header(default="")) -> None:
    """Rejects webhook calls that do not carry the shared secret configured on the Evolution instance."""
    expected = get_settings().webhook_secret
    if not hmac.compare_digest(x_webhook_secret.encode(), expected.encode()):
        raise AppException(ErrorCode.UNAUTHENTICATED)
