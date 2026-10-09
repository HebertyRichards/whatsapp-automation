import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import groupby
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppException
from app.models import Conversation, Customer, Fulfillment, PaymentMethod, PizzaSize, StoreSettings
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.customer_repository import CustomerRepository
from app.repositories.menu_repository import MenuRepository
from app.repositories.store_repository import StoreRepository
from app.schemas.conversation_schemas import Draft, DrinkItem, PendingPizza, PizzaItem, Step
from app.schemas.menu_schemas import MenuFlavor, MenuSection
from app.services.evolution_service import EvolutionService
from app.services.order_service import OrderService, StaleDraftError
from app.utils import messages
from app.utils.money import parse_brl
from app.utils.schedule import is_open, next_opening

logger = logging.getLogger(__name__)

# Silence longer than this ends the session; the next message starts over with the welcome.
SESSION_TIMEOUT = timedelta(minutes=30)

# How long the chat shows "typing..." before each reply, in milliseconds.
WELCOME_DELAY_MS = 4000
DEFAULT_DELAY_MS = 2000
PAGINATION_DELAY_MS = 1000

# Lists with up to PAGINATE_ABOVE entries go out whole; longer ones are split into pages of PAGE_SIZE.
PAGE_SIZE = 15
PAGINATE_ABOVE = 30

# Steps whose answer is typed freely, so only the exact one-character commands are intercepted.
_FREE_TEXT_STEPS = frozenset({Step.NAME, Step.ADDRESS, Step.CHANGE_AMOUNT})
_CHOICE = re.compile(r"\d{1,3}", re.ASCII)


@dataclass(frozen=True)
class Reply:
    text: str
    delay_ms: int = DEFAULT_DELAY_MS


class InvalidInputError(Exception):
    """The message is not an acceptable answer for the current step."""

    def __init__(self, hint: str = messages.INVALID) -> None:
        super().__init__(hint)
        self.hint = hint


@dataclass
class _Context:
    store: StoreSettings
    customer: Customer
    conv: Conversation
    draft: Draft
    push_name: str | None
    # Set once the conversation row is gone (order placed), so the draft is not written back.
    finished: bool = False


@dataclass(frozen=True)
class _Page:
    number: int
    start: int
    end: int
    count: int


_Handler = Callable[[_Context, str], Awaitable[list[Reply]]]


def _paginate(total: int, requested: int) -> _Page:
    if total <= PAGINATE_ABOVE:
        return _Page(0, 0, total, 1)
    count = -(-total // PAGE_SIZE)
    number = min(requested, count - 1)
    return _Page(number, number * PAGE_SIZE, min((number + 1) * PAGE_SIZE, total), count)


def _choice(answer: str) -> int | None:
    return int(answer) if _CHOICE.fullmatch(answer) else None


def _pick[T](choices: Sequence[T], answer: str) -> T:
    """The option the customer typed. Numbers are positions in the full list, not in the current page."""
    number = _choice(answer)
    if number is None or not 1 <= number <= len(choices):
        raise InvalidInputError
    return choices[number - 1]


def _required[T](value: T | None) -> T:
    if value is None:
        raise StaleDraftError
    return value


class ConversationService:
    """The ordering flow: one inbound message in, the replies to send out."""

    def __init__(self, db: AsyncSession, evolution: EvolutionService) -> None:
        self.db = db
        self.evolution = evolution
        self.store = StoreRepository(db)
        self.menu = MenuRepository(db)
        self.customers = CustomerRepository(db)
        self.conversations = ConversationRepository(db)
        self.orders = OrderService(db)
        self._handlers: dict[Step, _Handler] = {
            Step.MAIN_MENU: self._on_main_menu,
            Step.PIZZA_CATEGORY: self._on_category,
            Step.PIZZA_SIZE: self._on_size,
            Step.PIZZA_FLAVOR: self._on_flavor,
            Step.CART: self._on_cart,
            Step.CART_REMOVE: self._on_cart_remove,
            Step.DRINK: self._on_drink,
            Step.NAME: self._on_name,
            Step.FULFILLMENT: self._on_fulfillment,
            Step.ADDRESS: self._on_address,
            Step.PAYMENT: self._on_payment,
            Step.CHANGE: self._on_change,
            Step.CHANGE_AMOUNT: self._on_change_amount,
            Step.CONFIRM: self._on_confirm,
        }

    async def handle(self, jid: str, text: str | None, push_name: str | None) -> list[Reply]:
        """Advances the customer's conversation by one message. `text` is None for media."""
        store = await self.store.get_settings()
        if store is None:
            logger.error("store_settings is empty; run sql/store_setup.example.sql before using the bot")
            return []

        customer = await self.customers.get_or_create(jid)
        conv = await self.conversations.get(customer.id)
        now = datetime.now(UTC)
        if conv is None or now - conv.updated_at > SESSION_TIMEOUT:
            return await self._start_session(store, customer, conv, now)
        try:
            step = Step(conv.step)
            ctx = _Context(store, customer, conv, Draft.model_validate(conv.draft), push_name)
        except ValueError:
            # Step or draft written by an older version of the flow.
            return await self._start_session(store, customer, conv, now)

        conv.updated_at = now
        try:
            replies = await self._dispatch(ctx, step, text)
        except StaleDraftError:
            ctx.draft = Draft()
            replies = await self._go(ctx, Step.MAIN_MENU, notice=messages.RESTARTED)
        if not ctx.finished:
            conv.draft = ctx.draft.model_dump(mode="json")
        return replies

    async def _start_session(
        self, store: StoreSettings, customer: Customer, conv: Conversation | None, now: datetime
    ) -> list[Reply]:
        # Opening hours gate new sessions only: an order already in progress may finish after closing time.
        local_now = now.astimezone(ZoneInfo(store.timezone))
        hours = await self.store.list_opening_hours()
        if not is_open(hours, local_now):
            return [Reply(messages.closed(store.name, next_opening(hours, local_now), local_now))]

        fresh_draft = Draft().model_dump(mode="json")
        if conv is None:
            self.conversations.add(
                Conversation(customer_id=customer.id, step=Step.MAIN_MENU, draft=fresh_draft, updated_at=now)
            )
        else:
            conv.step, conv.draft, conv.invalid_count, conv.updated_at = Step.MAIN_MENU, fresh_draft, 0, now
        return [Reply(messages.welcome(store.name), WELCOME_DELAY_MS), Reply(messages.MAIN_MENU)]

    async def _dispatch(self, ctx: _Context, step: Step, text: str | None) -> list[Reply]:
        answer = (text or "").strip()
        command = answer.casefold()

        if step is Step.HANDOFF:
            # A human owns the chat; only the keyword hands it back to the bot.
            if command != "menu":
                return []
            ctx.draft = Draft()
            return await self._go(ctx, Step.MAIN_MENU)

        if text is None:
            return await self._invalid(ctx, messages.TEXT_ONLY)

        free_text = step in _FREE_TEXT_STEPS
        if command == "0" or (not free_text and "atendente" in command):
            return await self._handoff(ctx)
        if command == "v" or (not free_text and command == "voltar"):
            return await self._go(ctx, self._step_back(ctx, step))
        try:
            replies = await self._handlers[step](ctx, answer)
        except InvalidInputError as e:
            return await self._invalid(ctx, e.hint)
        ctx.conv.invalid_count = 0
        return replies

    # --- Step handlers: each receives the customer's answer and returns what to say next ---

    async def _on_main_menu(self, ctx: _Context, answer: str) -> list[Reply]:
        match _choice(answer):
            case 1:
                return await self._start_pizza(ctx)
            case 2:
                return [Reply(await self._menu_text()), await self._prompt(ctx)]
            case 3:
                return await self._handoff(ctx)
            case _:
                raise InvalidInputError

    async def _on_category(self, ctx: _Context, answer: str) -> list[Reply]:
        category = _pick(await self.menu.list_categories(), answer)
        ctx.draft.pending = PendingPizza(category_id=category.id)
        return await self._go(ctx, Step.PIZZA_SIZE)

    async def _on_size(self, ctx: _Context, answer: str) -> list[Reply]:
        pending = ctx.draft.pending
        size, half = _pick(await self._size_options(_required(pending.category_id)), answer)
        pending.size_id, pending.half, pending.first_flavor_id = size.id, half, None
        return await self._go(ctx, Step.PIZZA_FLAVOR)

    async def _on_flavor(self, ctx: _Context, answer: str) -> list[Reply]:
        pending = ctx.draft.pending
        size_id = _required(pending.size_id)
        flavors = await self.menu.list_flavors(_required(pending.category_id), size_id)
        if self._turn_page(ctx, answer, len(flavors)):
            return [await self._prompt(ctx, delay_ms=PAGINATION_DELAY_MS)]

        flavor, _ = _pick(flavors, answer)
        if pending.half and pending.first_flavor_id is None:
            pending.first_flavor_id = flavor.id
            return await self._go(ctx, Step.PIZZA_FLAVOR)

        flavor_ids = [flavor.id] if pending.first_flavor_id is None else [pending.first_flavor_id, flavor.id]
        ctx.draft.add(PizzaItem(size_id=size_id, half=pending.half, flavor_ids=flavor_ids))
        ctx.draft.pending = PendingPizza()
        return await self._go(ctx, Step.CART)

    async def _on_cart(self, ctx: _Context, answer: str) -> list[Reply]:
        match _choice(answer):
            case 1:
                return await self._start_pizza(ctx)
            case 2:
                if not await self.menu.list_drinks():
                    return [await self._prompt(ctx, notice=messages.NO_DRINKS)]
                return await self._go(ctx, Step.DRINK)
            case 3:
                return await self._go(ctx, Step.NAME)
            case 4:
                return await self._go(ctx, Step.CART_REMOVE)
            case _:
                raise InvalidInputError

    async def _on_cart_remove(self, ctx: _Context, answer: str) -> list[Reply]:
        ctx.draft.remove_one(_pick(ctx.draft.items, answer))
        if not ctx.draft.items:
            return await self._go(ctx, Step.MAIN_MENU, notice=messages.CART_EMPTIED)
        return await self._go(ctx, Step.CART)

    async def _on_drink(self, ctx: _Context, answer: str) -> list[Reply]:
        drinks = await self.menu.list_drinks()
        if self._turn_page(ctx, answer, len(drinks)):
            return [await self._prompt(ctx, delay_ms=PAGINATION_DELAY_MS)]
        ctx.draft.add(DrinkItem(drink_id=_pick(drinks, answer).id))
        return await self._go(ctx, Step.CART)

    async def _on_name(self, ctx: _Context, answer: str) -> list[Reply]:
        name = " ".join(answer.split())
        if not 2 <= len(name) <= 80 or not any(char.isalpha() for char in name):
            raise InvalidInputError(messages.NAME_INVALID)
        ctx.draft.name = name
        return await self._go(ctx, Step.FULFILLMENT)

    async def _on_fulfillment(self, ctx: _Context, answer: str) -> list[Reply]:
        match _choice(answer):
            case 1:
                ctx.draft.fulfillment, ctx.draft.address = Fulfillment.PICKUP, None
                return await self._go(ctx, Step.PAYMENT)
            case 2:
                ctx.draft.fulfillment = Fulfillment.DELIVERY
                return await self._go(ctx, Step.ADDRESS)
            case _:
                raise InvalidInputError

    async def _on_address(self, ctx: _Context, answer: str) -> list[Reply]:
        address = " ".join(answer.split())
        if not 5 <= len(address) <= 300:
            raise InvalidInputError(messages.ADDRESS_INVALID)
        ctx.draft.address = address
        return await self._go(ctx, Step.PAYMENT)

    async def _on_payment(self, ctx: _Context, answer: str) -> list[Reply]:
        match _choice(answer):
            case 1:
                ctx.draft.payment = PaymentMethod.CASH
                return await self._go(ctx, Step.CHANGE)
            case 2:
                ctx.draft.payment = PaymentMethod.CARD
            case 3:
                ctx.draft.payment = PaymentMethod.PIX
            case _:
                raise InvalidInputError
        ctx.draft.change_for = None
        return await self._go(ctx, Step.CONFIRM)

    async def _on_change(self, ctx: _Context, answer: str) -> list[Reply]:
        match _choice(answer):
            case 1:
                ctx.draft.change_for = None
                return await self._go(ctx, Step.CONFIRM)
            case 2:
                return await self._go(ctx, Step.CHANGE_AMOUNT)
            case _:
                raise InvalidInputError

    async def _on_change_amount(self, ctx: _Context, answer: str) -> list[Reply]:
        amount = parse_brl(answer)
        if amount is None:
            raise InvalidInputError(messages.AMOUNT_INVALID)
        total = (await self.orders.quote(ctx.draft, ctx.store)).total
        if amount <= total:
            raise InvalidInputError(messages.change_too_low(total))
        ctx.draft.change_for = amount
        return await self._go(ctx, Step.CONFIRM)

    async def _on_confirm(self, ctx: _Context, answer: str) -> list[Reply]:
        match _choice(answer):
            case 1:
                return await self._place_order(ctx)
            case 2:
                ctx.draft = Draft()
                return await self._go(ctx, Step.MAIN_MENU, notice=messages.ORDER_CANCELLED)
            case _:
                raise InvalidInputError

    # --- Shared moves ---

    async def _start_pizza(self, ctx: _Context) -> list[Reply]:
        if not await self.menu.list_categories():
            return [await self._prompt(ctx, notice=messages.MENU_UNAVAILABLE)]
        ctx.draft.pending = PendingPizza()
        return await self._go(ctx, Step.PIZZA_CATEGORY)

    async def _place_order(self, ctx: _Context) -> list[Reply]:
        checkout = _required(ctx.draft.checkout())
        quote = await self.orders.quote(ctx.draft, ctx.store)
        try:
            # The kitchen must hear about every stored order, so a failed alert rolls the order back.
            async with self.db.begin_nested():
                order = await self.orders.create(ctx.customer, quote, checkout)
                if ctx.store.staff_jid:
                    await self.evolution.send_text(
                        ctx.store.staff_jid,
                        messages.staff_order(order.id, quote, checkout, ctx.customer.jid),
                    )
        except AppException:
            logger.exception("Order rolled back: the staff could not be notified")
            return [await self._prompt(ctx, notice=messages.ORDER_FAILED)]

        ctx.customer.name = checkout.name
        await self.conversations.delete(ctx.conv)
        ctx.finished = True
        return [Reply(messages.order_confirmed(order.id, quote, checkout))]

    async def _handoff(self, ctx: _Context) -> list[Reply]:
        if ctx.store.staff_jid:
            name = ctx.draft.name or ctx.customer.name or ctx.push_name
            try:
                await self.evolution.send_text(ctx.store.staff_jid, messages.staff_handoff(name, ctx.customer.jid))
            except AppException:
                logger.exception("Could not alert the staff about an attendant request")
                return [await self._prompt(ctx, notice=messages.HANDOFF_FAILED)]
        ctx.conv.step = Step.HANDOFF
        return [Reply(messages.HANDOFF)]

    async def _invalid(self, ctx: _Context, hint: str) -> list[Reply]:
        ctx.conv.invalid_count += 1
        if ctx.conv.invalid_count >= 2:
            hint = f"{hint}\n{messages.ATTENDANT_TIP}"
        return [await self._prompt(ctx, notice=hint)]

    def _step_back(self, ctx: _Context, step: Step) -> Step:
        draft = ctx.draft
        match step:
            case Step.PIZZA_CATEGORY:
                return Step.CART if draft.items else Step.MAIN_MENU
            case Step.PIZZA_SIZE:
                return Step.PIZZA_CATEGORY
            case Step.PIZZA_FLAVOR:
                if draft.pending.first_flavor_id is None:
                    return Step.PIZZA_SIZE
                # Choosing the second half: go back to choosing the first one.
                draft.pending.first_flavor_id = None
                return Step.PIZZA_FLAVOR
            case Step.DRINK | Step.CART_REMOVE | Step.NAME:
                return Step.CART
            case Step.FULFILLMENT:
                return Step.NAME
            case Step.ADDRESS:
                return Step.FULFILLMENT
            case Step.PAYMENT:
                return Step.ADDRESS if draft.fulfillment is Fulfillment.DELIVERY else Step.FULFILLMENT
            case Step.CHANGE | Step.CONFIRM:
                return Step.PAYMENT
            case Step.CHANGE_AMOUNT:
                return Step.CHANGE
            case _:
                return step

    def _turn_page(self, ctx: _Context, answer: str, total: int) -> bool:
        """Applies M (next) / A (previous) to a paginated list. True when the page changed."""
        page = _paginate(total, ctx.draft.page)
        command = answer.casefold()
        if command in {"m", "mais"} and page.number + 1 < page.count:
            ctx.draft.page = page.number + 1
        elif command in {"a", "anterior"} and page.number > 0:
            ctx.draft.page = page.number - 1
        else:
            return False
        return True

    async def _go(self, ctx: _Context, step: Step, *, notice: str | None = None) -> list[Reply]:
        ctx.conv.step = step
        ctx.draft.page = 0
        return [await self._prompt(ctx, notice=notice)]

    # --- Rendering ---

    async def _prompt(self, ctx: _Context, *, notice: str | None = None, delay_ms: int = DEFAULT_DELAY_MS) -> Reply:
        """The current step's question, optionally preceded by a notice in the same message."""
        text = await self._render(ctx)
        return Reply(f"{notice}\n\n{text}" if notice else text, delay_ms)

    async def _render(self, ctx: _Context) -> str:
        draft = ctx.draft
        match Step(ctx.conv.step):
            case Step.MAIN_MENU:
                return messages.MAIN_MENU
            case Step.PIZZA_CATEGORY:
                return messages.categories([category.name for category in await self.menu.list_categories()])
            case Step.PIZZA_SIZE:
                choices = await self._size_options(_required(draft.pending.category_id))
                return messages.sizes([messages.size_label(size.name, half) for size, half in choices])
            case Step.PIZZA_FLAVOR:
                pending = draft.pending
                flavors = await self.menu.list_flavors(_required(pending.category_id), _required(pending.size_id))
                page = _paginate(len(flavors), draft.page)
                return messages.flavors(
                    [messages.priced(flavor.name, price) for flavor, price in flavors[page.start : page.end]],
                    first=page.start + 1,
                    nav=messages.page_nav(page.number, page.count),
                    half=pending.half,
                    choosing_second=pending.first_flavor_id is not None,
                    pricing=ctx.store.half_half_pricing,
                )
            case Step.CART:
                return messages.cart(await self.orders.quote(draft, ctx.store))
            case Step.CART_REMOVE:
                return messages.cart_remove(await self.orders.quote(draft, ctx.store))
            case Step.DRINK:
                drinks = await self.menu.list_drinks()
                page = _paginate(len(drinks), draft.page)
                return messages.drinks(
                    [messages.priced(drink.name, drink.price) for drink in drinks[page.start : page.end]],
                    first=page.start + 1,
                    nav=messages.page_nav(page.number, page.count),
                )
            case Step.NAME:
                return messages.NAME
            case Step.FULFILLMENT:
                return messages.fulfillment(ctx.store.delivery_fee)
            case Step.ADDRESS:
                return messages.ADDRESS
            case Step.PAYMENT:
                return messages.PAYMENT
            case Step.CHANGE:
                return messages.CHANGE
            case Step.CHANGE_AMOUNT:
                return messages.CHANGE_AMOUNT
            case Step.CONFIRM:
                quote = await self.orders.quote(draft, ctx.store)
                return messages.order_summary(quote, _required(draft.checkout()))
            case Step.HANDOFF:
                return messages.HANDOFF

    async def _size_options(self, category_id: int) -> list[tuple[PizzaSize, bool]]:
        """Each size as a whole pizza and, when the size allows it, as half-and-half."""
        choices: list[tuple[PizzaSize, bool]] = []
        for size in await self.menu.list_sizes(category_id):
            choices.append((size, False))
            if size.allows_half:
                choices.append((size, True))
        return choices

    async def _menu_text(self) -> str:
        sections = [
            MenuSection(
                name=category,
                flavors=[
                    MenuFlavor(
                        name=flavor.name,
                        description=flavor.description,
                        prices=[(size, price) for _, _, size, price in flavor_rows],
                    )
                    for flavor, flavor_rows in groupby(category_rows, key=lambda row: row[1])
                ],
            )
            for category, category_rows in groupby(await self.menu.list_offers(), key=lambda row: row[0])
        ]
        drinks = [(drink.name, drink.price) for drink in await self.menu.list_drinks()]
        if not sections and not drinks:
            return messages.MENU_UNAVAILABLE
        return messages.full_menu(sections, drinks)
