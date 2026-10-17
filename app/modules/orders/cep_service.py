import logging

import httpx

from app.modules.orders.schemas import DeliveryAddress
from app.utils.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

_URL = "https://viacep.com.br/ws/{cep}/json/"
_TIMEOUT_SECONDS = 5.0
_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0, name="viacep")


class CepUnavailableError(Exception):
    """The lookup could not be answered; the caller falls back to a typed address."""


class CepService:
    """Postal code lookup on ViaCEP (public, no key)."""

    async def find(self, cep: str) -> DeliveryAddress | None:
        """The address of an 8-digit postal code, or None when the code does not exist."""
        if not _breaker.allow():
            raise CepUnavailableError

        try:
            # One lookup per delivery order: a shared client would not pay for its lifecycle.
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                response = await client.get(_URL.format(cep=cep))
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as e:
            _breaker.record_failure()
            logger.warning("ViaCEP lookup failed: %s", e)
            raise CepUnavailableError from e

        _breaker.record_success()
        if not isinstance(body, dict) or body.get("erro"):
            return None
        return DeliveryAddress(
            cep=f"{cep[:5]}-{cep[5:]}",
            street=str(body.get("logradouro") or "").strip(),
            neighborhood=str(body.get("bairro") or "").strip(),
            city=str(body.get("localidade") or "").strip(),
            state=str(body.get("uf") or "").strip(),
        )
