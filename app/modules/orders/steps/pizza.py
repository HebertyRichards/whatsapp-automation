from app.modules.orders import messages
from app.modules.orders.menu_repository import MenuRepository
from app.modules.orders.models import PizzaSize
from app.modules.orders.order_service import OrderService
from app.modules.orders.schemas import OrderDraft, OrderStep, PendingPizza, PizzaItem
from app.schemas.conversation_schemas import CoreStep
from app.services.steps.base import (
    PAGINATION_DELAY_MS,
    Context,
    Move,
    StepHandler,
    paginate,
    pick,
    required,
    turn_page,
)
from app.utils.messages import page_nav, priced


async def start_pizza(menu: MenuRepository, draft: OrderDraft) -> Move:
    """Opens a new pizza, from the main menu or from the cart."""
    if not await menu.list_categories():
        return Move(notice=messages.MENU_UNAVAILABLE)
    draft.pending = PendingPizza()
    return Move(OrderStep.PIZZA_CATEGORY)


class CategoryStep(StepHandler[OrderDraft]):
    step = OrderStep.PIZZA_CATEGORY

    def __init__(self, menu: MenuRepository) -> None:
        self.menu = menu

    async def handle(self, ctx: Context[OrderDraft], answer: str) -> Move:
        category = pick(await self.menu.list_categories(), answer)
        ctx.draft.pending = PendingPizza(category_id=category.id)
        return Move(OrderStep.PIZZA_SIZE)

    async def render(self, ctx: Context[OrderDraft]) -> str:
        return messages.categories([category.name for category in await self.menu.list_categories()])

    def back(self, ctx: Context[OrderDraft]) -> str:
        return OrderStep.CART if ctx.draft.items else CoreStep.MAIN_MENU


class SizeStep(StepHandler[OrderDraft]):
    step = OrderStep.PIZZA_SIZE
    previous = OrderStep.PIZZA_CATEGORY

    def __init__(self, menu: MenuRepository) -> None:
        self.menu = menu

    async def handle(self, ctx: Context[OrderDraft], answer: str) -> Move:
        pending = ctx.draft.pending
        size, half = pick(await self._options(required(pending.category_id)), answer)
        pending.size_id, pending.half, pending.first_flavor_id = size.id, half, None
        return Move(OrderStep.PIZZA_FLAVOR)

    async def render(self, ctx: Context[OrderDraft]) -> str:
        choices = await self._options(required(ctx.draft.pending.category_id))
        return messages.sizes([messages.size_label(size.name, half) for size, half in choices])

    async def _options(self, category_id: int) -> list[tuple[PizzaSize, bool]]:
        """Each size as a whole pizza and, when the size allows it, as half-and-half."""
        choices: list[tuple[PizzaSize, bool]] = []
        for size in await self.menu.list_sizes(category_id):
            choices.append((size, False))
            if size.allows_half:
                choices.append((size, True))
        return choices


class FlavorStep(StepHandler[OrderDraft]):
    step = OrderStep.PIZZA_FLAVOR

    def __init__(self, menu: MenuRepository, orders: OrderService) -> None:
        self.menu = menu
        self.orders = orders

    async def handle(self, ctx: Context[OrderDraft], answer: str) -> Move:
        pending = ctx.draft.pending
        size_id = required(pending.size_id)
        flavors = await self.menu.list_flavors(required(pending.category_id), size_id)
        if turn_page(ctx.draft, answer, len(flavors)):
            return Move(delay_ms=PAGINATION_DELAY_MS)

        flavor, _ = pick(flavors, answer)
        if pending.half and pending.first_flavor_id is None:
            pending.first_flavor_id = flavor.id
            return Move(OrderStep.PIZZA_FLAVOR)

        flavor_ids = [flavor.id] if pending.first_flavor_id is None else [pending.first_flavor_id, flavor.id]
        ctx.draft.add(PizzaItem(size_id=size_id, half=pending.half, flavor_ids=flavor_ids))
        ctx.draft.pending = PendingPizza()
        return Move(OrderStep.CART)

    async def render(self, ctx: Context[OrderDraft]) -> str:
        pending = ctx.draft.pending
        flavors = await self.menu.list_flavors(required(pending.category_id), required(pending.size_id))
        page = paginate(len(flavors), ctx.draft.page)
        return messages.flavors(
            [priced(flavor.name, price) for flavor, price in flavors[page.start : page.end]],
            first=page.start + 1,
            nav=page_nav(page.number, page.count),
            half=pending.half,
            choosing_second=pending.first_flavor_id is not None,
            pricing=(await self.orders.settings()).half_half_pricing,
        )

    def back(self, ctx: Context[OrderDraft]) -> str:
        pending = ctx.draft.pending
        if pending.first_flavor_id is None:
            return OrderStep.PIZZA_SIZE
        pending.first_flavor_id = None
        return OrderStep.PIZZA_FLAVOR
