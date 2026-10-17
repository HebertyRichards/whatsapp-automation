import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.errors import AppException
from app.models import Conversation, Customer, StoreSettings
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.customer_repository import CustomerRepository
from app.repositories.store_repository import StoreRepository
from app.repositories.text_repository import TextRepository
from app.schemas.conversation_schemas import CoreStep, Draft
from app.services.flow import Flow
from app.services.messenger import Messenger
from app.services.steps.base import (
    DEFAULT_DELAY_MS,
    WELCOME_DELAY_MS,
    Context,
    InvalidInputError,
    Move,
    StaleDraftError,
    StepHandler,
)
from app.services.steps.menu import MainMenuStep
from app.utils import messages
from app.utils.schedule import is_open, next_opening
from app.utils.texts import Texts

logger = logging.getLogger(__name__)

# Silence longer than this ends the session; the next message starts over with the welcome.
SESSION_TIMEOUT = timedelta(minutes=30)
# Same, while a human owns the chat. Messages from the customer and from the attendant both count.
HANDOFF_TIMEOUT = timedelta(minutes=15)

type Steps = Mapping[str, StepHandler[Any]]


@dataclass(frozen=True)
class Reply:
    text: str
    delay_ms: int = DEFAULT_DELAY_MS


@dataclass(frozen=True)
class _Arrival:
    """What is known about an inbound message before its conversation is opened."""

    store: StoreSettings
    customer: Customer
    push_name: str | None
    texts: Texts
    now: datetime

    def context[D: Draft](self, conv: Conversation, draft: D) -> Context[D]:
        return Context(self.store, self.customer, conv, draft, self.push_name, self.texts)


def _expired(conv: Conversation, now: datetime) -> bool:
    limit = HANDOFF_TIMEOUT if conv.step == CoreStep.HANDOFF else SESSION_TIMEOUT
    return now - conv.updated_at > limit


class ConversationService:
    """Runs a conversation: one inbound message in, the replies to send out.

    It owns the session, the main menu, the commands valid everywhere and the hand-off to a human.
    The business module picked by `store_settings.business_type` owns every other step.
    """

    def __init__(
        self,
        store: StoreRepository,
        customers: CustomerRepository,
        conversations: ConversationRepository,
        texts: TextRepository,
        messenger: Messenger,
        flows: Mapping[str, Callable[[], Flow[Any]]],
    ) -> None:
        self.store = store
        self.customers = customers
        self.conversations = conversations
        self.texts = texts
        self.messenger = messenger
        self.flows = flows

    async def handle(
        self, jid: str, text: str | None, push_name: str | None, *, during_reply: bool = False
    ) -> list[Reply]:
        """Advances the customer's conversation by one message. `text` is None for media.

        `during_reply` marks a message sent while the bot was still answering an earlier one, before its question
        arrived. It is acted on when it is a valid answer and gets no reply otherwise, so a burst of messages is
        not met with a burst of "não entendi".
        """
        store = await self.store.get_settings()
        if store is None:
            logger.error("store_settings is empty; run one of the sql/*.example.sql files before using the bot")
            return []
        build = self.flows.get(store.business_type)
        if build is None:
            logger.error("business_type %r is not one of: %s", store.business_type, ", ".join(self.flows))
            return []
        flow = build()
        steps: Steps = {handler.step: handler for handler in (MainMenuStep(flow), *flow.steps())}

        customer = await self.customers.get_or_create(jid)
        conv = await self.conversations.get(customer.id)
        arrival = _Arrival(store, customer, push_name, Texts(await self.texts.overrides()), datetime.now(UTC))
        if conv is None or _expired(conv, arrival.now):
            if during_reply:
                # The welcome, the closed notice or the order confirmation is on its way; another would repeat it.
                return []
            return await self._start_session(arrival, flow, steps, conv)
        try:
            ctx = arrival.context(conv, flow.draft(conv.draft))
        except ValueError:
            # Draft written by an older version of the module.
            return await self._start_session(arrival, flow, steps, conv)
        if conv.step != CoreStep.HANDOFF and conv.step not in steps:
            # Step of an older version of the module, or of another module.
            return await self._start_session(arrival, flow, steps, conv)

        conv.updated_at = arrival.now
        try:
            replies = await self._dispatch(ctx, steps, text, during_reply)
        except StaleDraftError:
            ctx.draft = flow.draft()
            replies = await self._go(ctx, steps, CoreStep.MAIN_MENU, notice=messages.RESTARTED)
        if not ctx.finished:
            conv.draft = ctx.draft.model_dump(mode="json")
        return replies

    async def human_takeover(self, jid: str) -> None:
        """An attendant wrote in this chat: the bot stays out until it goes quiet or the customer types `menu`.

        Applies with or without an open session, so a customer answering the attendant is not greeted by the bot.
        """
        customer = await self.customers.get_or_create(jid)
        conv = await self.conversations.get(customer.id)
        now = datetime.now(UTC)
        if conv is None:
            draft = Draft().model_dump(mode="json")
            conv = Conversation(customer_id=customer.id, step=CoreStep.HANDOFF, draft=draft, updated_at=now)
            self.conversations.add(conv)
        else:
            conv.step, conv.updated_at = CoreStep.HANDOFF, now

    async def _start_session(
        self, arrival: _Arrival, flow: Flow[Any], steps: Steps, conv: Conversation | None
    ) -> list[Reply]:
        # Opening hours gate new sessions only: an order already in progress may finish after closing time.
        store, texts = arrival.store, arrival.texts
        local_now = arrival.now.astimezone(ZoneInfo(store.timezone))
        hours = await self.store.list_opening_hours()
        if not is_open(hours, local_now):
            return [Reply(messages.closed(texts, store.name, next_opening(hours, local_now), local_now))]

        draft = flow.draft()
        fresh = draft.model_dump(mode="json")
        if conv is None:
            conv = Conversation(customer_id=arrival.customer.id, step=CoreStep.MAIN_MENU, draft=fresh)
            conv.updated_at = arrival.now
            self.conversations.add(conv)
        else:
            conv.step, conv.draft, conv.invalid_count, conv.updated_at = CoreStep.MAIN_MENU, fresh, 0, arrival.now
        ctx = arrival.context(conv, draft)
        welcome = Reply(texts(flow.welcome, loja=store.name), WELCOME_DELAY_MS)
        return [welcome, await self._prompt(ctx, steps)]

    async def _dispatch(self, ctx: Context[Any], steps: Steps, text: str | None, during_reply: bool) -> list[Reply]:
        answer = (text or "").strip()
        command = answer.casefold()

        if ctx.conv.step == CoreStep.HANDOFF:
            # A human owns the chat; only the keyword hands it back to the bot.
            if command != "menu":
                return []
            ctx.draft = type(ctx.draft)()
            return await self._go(ctx, steps, CoreStep.MAIN_MENU)

        if text is None:
            return [] if during_reply else await self._invalid(ctx, steps, messages.TEXT_ONLY)

        handler = steps[ctx.conv.step]
        if command == "0" or (not handler.free_text and "atendente" in command):
            return await self._handoff(ctx, steps)
        if command == "v" or (not handler.free_text and command == "voltar"):
            return await self._go(ctx, steps, handler.back(ctx))
        try:
            replies = await self._apply(ctx, steps, await handler.handle(ctx, answer))
        except InvalidInputError as e:
            # The customer had not seen the question yet, so this was not an answer to it.
            return [] if during_reply else await self._invalid(ctx, steps, e.hint)
        ctx.conv.invalid_count = 0
        return replies

    async def _apply(self, ctx: Context[Any], steps: Steps, move: Move) -> list[Reply]:
        """Carries out what a step decided."""
        if move.step == CoreStep.HANDOFF:
            return await self._handoff(ctx, steps)
        said = [Reply(ctx.texts(text)) for text in move.say]
        if move.ends:
            await self.conversations.delete(ctx.conv)
            ctx.finished = True
            return said
        if move.step is not None:
            ctx.conv.step = move.step
            ctx.draft.page = 0
        return [*said, await self._prompt(ctx, steps, notice=move.notice, delay_ms=move.delay_ms)]

    async def _go(self, ctx: Context[Any], steps: Steps, step: str, *, notice: str | None = None) -> list[Reply]:
        return await self._apply(ctx, steps, Move(step, notice=notice))

    async def _handoff(self, ctx: Context[Any], steps: Steps) -> list[Reply]:
        if ctx.store.staff_jid:
            name = ctx.draft.name or ctx.customer.name or ctx.push_name
            try:
                await self.messenger.send_text(ctx.store.staff_jid, messages.staff_handoff(name, ctx.customer.jid))
            except AppException:
                logger.exception("Could not alert the staff about an attendant request")
                return [await self._prompt(ctx, steps, notice=messages.HANDOFF_FAILED)]
        ctx.conv.step = CoreStep.HANDOFF
        return [Reply(ctx.texts(messages.HANDOFF))]

    async def _invalid(self, ctx: Context[Any], steps: Steps, hint: str) -> list[Reply]:
        ctx.conv.invalid_count += 1
        notice = ctx.texts(hint)
        if ctx.conv.invalid_count >= 2:
            notice = f"{notice}\n{ctx.texts(messages.ATTENDANT_TIP)}"
        return [await self._prompt(ctx, steps, notice=notice)]

    async def _prompt(
        self, ctx: Context[Any], steps: Steps, *, notice: str | None = None, delay_ms: int = DEFAULT_DELAY_MS
    ) -> Reply:
        """The current step's question, optionally preceded by a notice in the same message."""
        text = await steps[ctx.conv.step].render(ctx)
        return Reply(f"{ctx.texts(notice)}\n\n{text}" if notice else text, delay_ms)
