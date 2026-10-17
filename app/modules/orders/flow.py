from collections.abc import Mapping, Sequence
from itertools import groupby
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders import messages
from app.modules.orders.cep_service import CepService
from app.modules.orders.menu_repository import MenuRepository
from app.modules.orders.order_repository import OrderRepository
from app.modules.orders.order_service import OrderService
from app.modules.orders.schemas import MenuFlavor, MenuSection, OrderDraft
from app.modules.orders.steps.address import (
    AddressComplementStep,
    AddressComplementTextStep,
    AddressConfirmStep,
    AddressNumberStep,
    CepStep,
    TypedAddressStep,
)
from app.modules.orders.steps.cart import CartRemoveStep, CartStep, DrinkStep
from app.modules.orders.steps.checkout import (
    ChangeAmountStep,
    ChangeStep,
    ConfirmStep,
    FulfillmentStep,
    OrderNameStep,
    PaymentStep,
)
from app.modules.orders.steps.pizza import CategoryStep, FlavorStep, SizeStep, start_pizza
from app.services.flow import Flow
from app.services.messenger import Messenger
from app.services.steps.base import Context, Move, StepHandler

# Shared across sessions: it keeps the ViaCEP circuit breaker state.
_cep = CepService()


class OrdersFlow(Flow[OrderDraft]):
    """Menu, cart, delivery or pickup, payment and the order sent to the kitchen."""

    welcome = messages.WELCOME
    start_label = messages.START_LABEL
    catalog_label = messages.CATALOG_LABEL

    def __init__(self, db: AsyncSession, messenger: Messenger) -> None:
        self.menu = MenuRepository(db)
        self.orders = OrderService(db, self.menu, OrderRepository(db), messenger)

    def draft(self, data: Mapping[str, Any] | None = None) -> OrderDraft:
        return OrderDraft() if data is None else OrderDraft.model_validate(data)

    def steps(self) -> Sequence[StepHandler[OrderDraft]]:
        return (
            CategoryStep(self.menu),
            SizeStep(self.menu),
            FlavorStep(self.menu, self.orders),
            CartStep(self.menu, self.orders),
            CartRemoveStep(self.orders),
            DrinkStep(self.menu),
            OrderNameStep(),
            FulfillmentStep(self.orders),
            CepStep(_cep),
            AddressConfirmStep(),
            AddressNumberStep(),
            AddressComplementStep(),
            AddressComplementTextStep(),
            TypedAddressStep(),
            PaymentStep(),
            ChangeStep(),
            ChangeAmountStep(self.orders),
            ConfirmStep(self.orders),
        )

    async def start(self, ctx: Context[OrderDraft]) -> Move:
        return await start_pizza(self.menu, ctx.draft)

    async def catalog(self, ctx: Context[OrderDraft]) -> str:
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
            return ctx.texts(messages.MENU_UNAVAILABLE)
        return messages.full_menu(sections, drinks)
