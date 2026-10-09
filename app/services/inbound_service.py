import asyncio
import logging

from pydantic import ValidationError

from app.config.database import SessionLocal
from app.config.settings import get_settings
from app.errors import AppException
from app.schemas.webhook_schemas import InboundMessage, WebhookEvent
from app.services.conversation_service import ConversationService
from app.services.evolution_service import EvolutionService
from app.utils import rate_limit
from app.utils.keyed_lock import KeyedLock

logger = logging.getLogger(__name__)

_MESSAGES_UPSERT = "messages.upsert"
# One-to-one chats only: groups, broadcasts and channels never talk to the bot.
_DIRECT_CHAT_SUFFIXES = ("@s.whatsapp.net", "@lid")
# Non-text content a customer may send; anything else (reactions, protocol messages) is noise.
_MEDIA_TYPES = frozenset(
    {
        "audioMessage",
        "imageMessage",
        "videoMessage",
        "ptvMessage",
        "documentMessage",
        "stickerMessage",
        "locationMessage",
        "liveLocationMessage",
        "contactMessage",
        "contactsArrayMessage",
    }
)
# Evolution replays the backlog after a reconnect; answering it would fire a burst of late replies.
_STALE_AFTER_SECONDS = 600
_SHUTDOWN_GRACE_SECONDS = 20


class InboundService:
    """Turns webhook events into conversation turns, one customer at a time."""

    def __init__(self) -> None:
        self._evolution = EvolutionService()
        self._locks = KeyedLock()
        # Strong references: the event loop only keeps weak ones to running tasks.
        self._tasks: set[asyncio.Task[None]] = set()

    async def accept(self, event: WebhookEvent) -> bool:
        """Queues the message and returns at once, so the webhook is acknowledged before any reply is typed.

        False means the event was ignored on purpose.
        """
        if event.event != _MESSAGES_UPSERT or event.instance != get_settings().evolution_instance:
            return False
        try:
            message = InboundMessage.model_validate(event.data)
        except ValidationError:
            logger.warning("Ignoring a messages.upsert event with an unexpected payload")
            return False

        jid = message.key.remoteJid
        if message.key.fromMe or not jid.endswith(_DIRECT_CHAT_SUFFIXES):
            return False
        text = message.text
        if text is None and message.messageType not in _MEDIA_TYPES:
            return False
        if message.is_older_than(_STALE_AFTER_SECONDS):
            logger.info("Ignoring a stale message from %s", jid)
            return False
        if not await rate_limit.first_delivery(message.key.id):
            return False
        if not await rate_limit.allow_message(jid):
            logger.warning("Rate limit reached for %s; message dropped", jid)
            return False

        task = asyncio.create_task(self._process(jid, text, message.pushName))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def _process(self, jid: str, text: str | None, push_name: str | None) -> None:
        # The lock covers the sends too, so a customer's next message waits for the replies to this one.
        async with self._locks.hold(jid):
            try:
                async with SessionLocal() as session:
                    replies = await ConversationService(session, self._evolution).handle(jid, text, push_name)
                    await session.commit()
            except Exception:
                logger.exception("Could not process a message from %s", jid)
                return

            for reply in replies:
                try:
                    await self._evolution.send_text(jid, reply.text, reply.delay_ms)
                except AppException as e:
                    logger.error("Reply to %s was not delivered: %s", jid, e.message)
                    return

    async def shutdown(self) -> None:
        """Gives in-flight conversations a moment to finish replying."""
        if self._tasks:
            await asyncio.wait(self._tasks, timeout=_SHUTDOWN_GRACE_SECONDS)


_inbound_service = InboundService()


def get_inbound_service() -> InboundService:
    return _inbound_service
