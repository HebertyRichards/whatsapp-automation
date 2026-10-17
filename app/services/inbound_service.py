import asyncio
import logging
from collections import Counter
from collections.abc import Callable, Coroutine

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import SessionLocal
from app.config.settings import get_settings
from app.errors import AppException
from app.schemas.webhook_schemas import InboundMessage, WebhookEvent
from app.services.conversation_service import ConversationService
from app.services.evolution_service import sent_by_bot
from app.services.messenger import Messenger
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

    def __init__(self, messenger: Messenger, conversation: Callable[[AsyncSession], ConversationService]) -> None:
        self._messenger = messenger
        self._conversation = conversation
        self._locks = KeyedLock()
        self._answering: Counter[str] = Counter()
        # Strong references: the event loop only keeps weak ones to running tasks.
        self._tasks: set[asyncio.Task[None]] = set()

    async def accept(self, event: WebhookEvent) -> bool:
        """Queues the message and returns at once, so the webhook is acknowledged before any reply is typed.

        False means the event was ignored on purpose. Every call logs one line saying why.
        """
        queued, reason = await self._triage(event)
        logger.info("Webhook %s %s: %s", event.event, "queued" if queued else "ignored", reason)
        return queued

    async def _triage(self, event: WebhookEvent) -> tuple[bool, str]:
        if event.event != _MESSAGES_UPSERT:
            return False, "not a new message"
        if event.instance != get_settings().evolution_instance:
            return False, f"instance {event.instance!r} is not this bot's"
        try:
            message = InboundMessage.model_validate(event.data)
        except ValidationError:
            return False, "unexpected payload"

        jid = message.key.remoteJid
        if not jid.endswith(_DIRECT_CHAT_SUFFIXES):
            return False, f"{jid} is not a one-to-one chat"
        text = message.text
        if text is None and message.messageType not in _MEDIA_TYPES:
            return False, f"{jid} sent a {message.messageType}, nothing to answer"
        age = message.age_seconds()
        # How late the message reached the bot: a delay here comes from before the bot, not from it.
        arrived = f"{jid}, {'age unknown' if age is None else f'{age}s after it was sent'}"
        if message.is_older_than(_STALE_AFTER_SECONDS):
            return False, f"stale message from {arrived}"
        if not await rate_limit.first_delivery(message.key.id):
            return False, f"repeated delivery of {message.key.id} from {arrived}"
        if message.key.fromMe:
            self._spawn(self._takeover(jid, message.key.id))
            return True, f"written by the store in the chat with {arrived}"
        if not rate_limit.allow_message(jid):
            return False, f"rate limit reached by {arrived}"

        during_reply = self._answering[jid] > 0
        self._answering[jid] += 1
        self._spawn(self._process(jid, text, message.pushName, during_reply))
        return True, f"customer message from {arrived}" + (", sent during a reply" if during_reply else "")

    def _spawn(self, work: Coroutine[None, None, None]) -> None:
        task = asyncio.create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _takeover(self, jid: str, message_id: str) -> None:
        # Same lock as the replies: an echo of the bot's own message is only judged after its id is known.
        async with self._locks.hold(jid):
            if sent_by_bot(message_id):
                return
            try:
                async with SessionLocal() as session:
                    await self._conversation(session).human_takeover(jid)
                    await session.commit()
            except Exception:
                logger.exception("Could not hand the chat with %s over to the attendant", jid)
                return
            logger.info("Attendant wrote to %s; the bot stays out of this chat", jid)

    async def _process(self, jid: str, text: str | None, push_name: str | None, during_reply: bool) -> None:
        try:
            async with self._locks.hold(jid):
                try:
                    async with SessionLocal() as session:
                        replies = await self._conversation(session).handle(
                            jid, text, push_name, during_reply=during_reply
                        )
                        await session.commit()
                except Exception:
                    logger.exception("Could not process a message from %s", jid)
                    return

                for reply in replies:
                    try:
                        await self._messenger.send_text(jid, reply.text, reply.delay_ms)
                    except AppException as e:
                        logger.error("Reply to %s was not delivered: %s", jid, e.message)
                        return
        finally:
            self._answering[jid] -= 1
            if not self._answering[jid]:
                del self._answering[jid]

    async def shutdown(self) -> None:
        """Gives in-flight conversations a moment to finish replying."""
        if self._tasks:
            await asyncio.wait(self._tasks, timeout=_SHUTDOWN_GRACE_SECONDS)
