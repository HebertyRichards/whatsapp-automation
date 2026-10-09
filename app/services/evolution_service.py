import logging

import httpx

from app.config.settings import get_settings
from app.errors import AppException, ErrorCode
from app.utils.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

# Added on top of the typing delay, which Evolution waits out before it answers the request.
_TIMEOUT_SECONDS = 15.0

# One client for the whole process: a new AsyncClient per call would redo DNS + TCP + TLS every time.
_client: httpx.AsyncClient | None = None
_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0, name="evolution")


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient()
    return _client


async def close_evolution_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


class EvolutionService:
    """Outbound HTTP client for the Evolution API."""

    async def send_text(self, jid: str, text: str, delay_ms: int = 0) -> None:
        """Sends a text message. With `delay_ms`, the chat shows "typing..." for that long first."""
        if not _breaker.allow():
            raise AppException(ErrorCode.EVOLUTION_UNAVAILABLE)

        settings = get_settings()
        try:
            response = await _http().post(
                f"{settings.evolution_api_url}/message/sendText/{settings.evolution_instance}",
                headers={"apikey": settings.evolution_api_key},
                # The full JID is sent as received: Evolution rewrites bare Brazilian numbers (ninth digit).
                json={"number": jid, "text": text, "delay": delay_ms, "linkPreview": False},
                timeout=_TIMEOUT_SECONDS + delay_ms / 1000,
            )
        except httpx.HTTPError as e:
            _breaker.record_failure()
            raise AppException(ErrorCode.EVOLUTION_UNAVAILABLE) from e

        if response.status_code >= 500:
            _breaker.record_failure()
            logger.error("Evolution failed on sendText (%s): %s", response.status_code, response.text)
            raise AppException(ErrorCode.EVOLUTION_UNAVAILABLE)

        _breaker.record_success()
        if response.is_error:
            logger.error("Evolution rejected sendText (%s): %s", response.status_code, response.text)
            raise AppException(ErrorCode.EVOLUTION_REJECTED)
