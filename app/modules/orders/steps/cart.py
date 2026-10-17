from app.modules.orders import messages
from app.modules.orders.menu_repository import MenuRepository
from app.modules.orders.order_service import OrderService
from app.modules.orders.schemas import DrinkItem, OrderDraft, OrderStep
from app.modules.orders.steps.pizza import start_pizza
from app.schemas.conversation_schemas import CoreStep
from app.services.steps.base import (
    PAGINATION_DELAY_MS,
    Context,
    InvalidInputError,
    Move,
    StepHandler,
    choice,
    paginate,
    pick,
    turn_page,
)
from app.utils.messages import page_nav, priced


class CartStep(StepHandler[OrderDraft]):
    step = OrderStep.CART

    def __init__(self, menu: MenuRepository, orders: OrderService) -> None:
        self.menu = menu
        self.orders = orders

    async def handle(self, ctx: Context[OrderDraft], answer: str) -> Move:
        match choice(answer):
            case 1:
                return await start_pizza(self.menu, ctx.draft)
            case 2:
                if not await self.menu.list_drinks():
                    return Move(notice=messages.NO_DRINKS)
                return Move(OrderStep.DRINK)
            case 3:
                return Move(OrderStep.NAME)
            case 4:
                return Move(OrderStep.CART_REMOVE)
            case _:
                raise InvalidInputError

    async def render(self, ctx: Context[OrderDraft]) -> str:
        return messages.cart(await self.orders.quote(ctx.draft))


class CartRemoveStep(StepHandler[OrderDraft]):
    step = OrderStep.CART_REMOVE
    previous = OrderStep.CART

    def __init__(self, orders: OrderService) -> None:
        self.orders = orders

    async def handle(self, ctx: Context[OrderDraft], answer: str) -> Move:
        ctx.draft.remove_one(pick(ctx.draft.items, answer))
        if not ctx.draft.items:
            return Move(CoreStep.MAIN_MENU, notice=messages.CART_EMPTIED)
        return Move(OrderStep.CART)

    async def render(self, ctx: Context[OrderDraft]) -> str:
        return messages.cart_remove(await self.orders.quote(ctx.draft))


class DrinkStep(StepHandler[OrderDraft]):
    step = OrderStep.DRINK
    previous = OrderStep.CART

    def __init__(self, menu: MenuRepository) -> None:
        self.menu = menu

    async def handle(self, ctx: Context[OrderDraft], answer: str) -> Move:
        drinks = await self.menu.list_drinks()
        if turn_page(ctx.draft, answer, len(drinks)):
            return Move(delay_ms=PAGINATION_DELAY_MS)
        ctx.draft.add(DrinkItem(drink_id=pick(drinks, answer).id))
        return Move(OrderStep.CART)

    async def render(self, ctx: Context[OrderDraft]) -> str:
        drinks = await self.menu.list_drinks()
        page = paginate(len(drinks), ctx.draft.page)
        return messages.drinks(
            [priced(drink.name, drink.price) for drink in drinks[page.start : page.end]],
            first=page.start + 1,
            nav=page_nav(page.number, page.count),
        )
