from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, Fulfillment, HalfHalfPricing, Order, OrderItem, StoreSettings
from app.repositories.menu_repository import MenuRepository
from app.repositories.order_repository import OrderRepository
from app.schemas.conversation_schemas import Checkout, Draft, DrinkItem, PizzaItem
from app.schemas.order_schemas import Quote, QuoteLine
from app.utils import messages

_CENT = Decimal("0.01")


class StaleDraftError(Exception):
    """The saved draft no longer matches the menu, or lacks data the current step relies on."""


def half_half_price(rule: HalfHalfPricing, first: Decimal, second: Decimal) -> Decimal:
    """Price of a pizza split between two flavors. The only place this business rule lives."""
    if rule is HalfHalfPricing.AVERAGE:
        return ((first + second) / 2).quantize(_CENT, rounding=ROUND_HALF_UP)
    return max(first, second)


class OrderService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.menu = MenuRepository(db)
        self.orders = OrderRepository(db)

    async def quote(self, draft: Draft, store: StoreSettings) -> Quote:
        """Prices the draft from the current menu, so no total ever comes from stored numbers."""
        pizzas = [item for item in draft.items if isinstance(item, PizzaItem)]
        size_ids = {pizza.size_id for pizza in pizzas}
        flavor_ids = {flavor_id for pizza in pizzas for flavor_id in pizza.flavor_ids}
        sizes = await self.menu.get_sizes(size_ids)
        flavors = await self.menu.get_flavors(flavor_ids)
        prices = await self.menu.get_prices(flavor_ids, size_ids)
        drinks = await self.menu.get_drinks({item.drink_id for item in draft.items if isinstance(item, DrinkItem)})

        lines: list[QuoteLine] = []
        try:
            for item in draft.items:
                if isinstance(item, DrinkItem):
                    drink = drinks[item.drink_id]
                    lines.append(
                        QuoteLine(
                            description=drink.name,
                            quantity=item.quantity,
                            unit_price=drink.price,
                            drink_id=drink.id,
                        )
                    )
                    continue

                size = sizes[item.size_id]
                # A whole pizza has one flavor, so both ends are the same and either rule yields its price.
                first, second = item.flavor_ids[0], item.flavor_ids[-1]
                names = [flavors[flavor_id].name for flavor_id in item.flavor_ids]
                lines.append(
                    QuoteLine(
                        description=messages.pizza_description(size.name, item.half, names),
                        quantity=item.quantity,
                        unit_price=half_half_price(
                            store.half_half_pricing, prices[first, size.id], prices[second, size.id]
                        ),
                        size_id=size.id,
                        flavor_id=first,
                        second_flavor_id=second if item.half else None,
                    )
                )
        except (KeyError, IndexError) as e:
            raise StaleDraftError from e

        delivery_fee = store.delivery_fee if draft.fulfillment is Fulfillment.DELIVERY else Decimal("0")
        return Quote(lines=lines, delivery_fee=delivery_fee)

    async def create(self, customer: Customer, quote: Quote, checkout: Checkout) -> Order:
        order = Order(
            customer_id=customer.id,
            customer_name=checkout.name,
            fulfillment=checkout.fulfillment,
            address=checkout.address,
            payment_method=checkout.payment,
            change_for=checkout.change_for,
            subtotal=quote.subtotal,
            delivery_fee=quote.delivery_fee,
            total=quote.total,
            items=[
                OrderItem(
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    pizza_size_id=line.size_id,
                    flavor_id=line.flavor_id,
                    second_flavor_id=line.second_flavor_id,
                    drink_id=line.drink_id,
                )
                for line in quote.lines
            ],
        )
        return await self.orders.add(order)
