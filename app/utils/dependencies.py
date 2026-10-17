import hmac
from collections.abc import Mapping
from functools import partial

from fastapi import Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.errors import AppException, ErrorCode
from app.modules.orders.flow import OrdersFlow
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.customer_repository import CustomerRepository
from app.repositories.store_repository import StoreRepository
from app.repositories.text_repository import TextRepository
from app.services.conversation_service import ConversationService
from app.services.evolution_service import EvolutionService
from app.services.flow import FlowFactory
from app.services.inbound_service import InboundService
from app.services.messenger import Messenger

# The only place that names the concrete classes: swapping the provider or adding a module is a change here.
_messenger: Messenger = EvolutionService()

# Modules by `store_settings.business_type`.
FLOWS: dict[str, FlowFactory] = {
    "orders": OrdersFlow,
}


def build_conversation_service(
    db: AsyncSession, messenger: Messenger, flows: Mapping[str, FlowFactory] = FLOWS
) -> ConversationService:
    return ConversationService(
        store=StoreRepository(db),
        customers=CustomerRepository(db),
        conversations=ConversationRepository(db),
        texts=TextRepository(db),
        messenger=messenger,
        flows={name: partial(build, db, messenger) for name, build in flows.items()},
    )


_inbound_service = InboundService(_messenger, partial(build_conversation_service, messenger=_messenger))


def get_inbound_service() -> InboundService:
    return _inbound_service


async def verify_webhook_secret(x_webhook_secret: str = Header(default="")) -> None:
    """Rejects webhook calls that do not carry the shared secret configured on the Evolution instance."""
    expected = get_settings().webhook_secret
    if not hmac.compare_digest(x_webhook_secret.encode(), expected.encode()):
        raise AppException(ErrorCode.UNAUTHENTICATED)
