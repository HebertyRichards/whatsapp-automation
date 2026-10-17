from fastapi import APIRouter, Depends, status

from app.schemas.webhook_schemas import WebhookAck, WebhookEvent
from app.services.inbound_service import InboundService
from app.utils.dependencies import get_inbound_service, verify_webhook_secret

webhook_tag_metadata = {
    "name": "Webhook",
    "description": "Events pushed by the Evolution API.",
}

webhook_routes = APIRouter(prefix="/webhook", tags=[webhook_tag_metadata["name"]])


@webhook_routes.post(
    "/evolution",
    response_model=WebhookAck,
    status_code=status.HTTP_200_OK,
    summary="Receives an Evolution API event",
    dependencies=[Depends(verify_webhook_secret)],
)
async def receive_evolution_event(
    event: WebhookEvent,
    inbound_service: InboundService = Depends(get_inbound_service),
) -> WebhookAck:
    queued = await inbound_service.accept(event)
    return WebhookAck(status="queued" if queued else "ignored")
