from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.orders.models import Fulfillment, PaymentMethod
from app.schemas.conversation_schemas import Draft


class OrderStep(StrEnum):
    PIZZA_CATEGORY = "pizza_category"
    PIZZA_SIZE = "pizza_size"
    PIZZA_FLAVOR = "pizza_flavor"
    CART = "cart"
    CART_REMOVE = "cart_remove"
    DRINK = "drink"
    NAME = "name"
    FULFILLMENT = "fulfillment"
    ADDRESS_CEP = "address_cep"
    ADDRESS_CONFIRM = "address_confirm"
    ADDRESS_NUMBER = "address_number"
    ADDRESS_COMPLEMENT = "address_complement"
    ADDRESS_COMPLEMENT_TEXT = "address_complement_text"
    ADDRESS = "address"
    PAYMENT = "payment"
    CHANGE = "change"
    CHANGE_AMOUNT = "change_amount"
    CONFIRM = "confirm"


class PizzaItem(BaseModel):
    kind: Literal["pizza"] = "pizza"
    size_id: int
    half: bool
    # One id for a whole pizza, two for half-and-half.
    flavor_ids: list[int]
    quantity: int = 1


class DrinkItem(BaseModel):
    kind: Literal["drink"] = "drink"
    drink_id: int
    quantity: int = 1


CartItem = Annotated[PizzaItem | DrinkItem, Field(discriminator="kind")]


class PendingPizza(BaseModel):
    """The pizza being assembled across the category, size and flavor steps."""

    category_id: int | None = None
    size_id: int | None = None
    half: bool = False
    first_flavor_id: int | None = None


class DeliveryAddress(BaseModel):
    """Address found by postal code, completed with the number and complement the customer types."""

    cep: str
    street: str
    neighborhood: str
    city: str
    state: str
    number: str | None = None
    complement: str | None = None


class Checkout(BaseModel):
    """Checkout answers, once all of them are known."""

    name: str
    fulfillment: Fulfillment
    address: str | None
    payment: PaymentMethod
    change_for: Decimal | None


class OrderDraft(Draft):
    """In-progress order. It holds ids only: prices always come from the menu."""

    items: list[CartItem] = Field(default_factory=list)
    pending: PendingPizza = PendingPizza()
    fulfillment: Fulfillment | None = None
    lookup: DeliveryAddress | None = None
    address: str | None = None
    payment: PaymentMethod | None = None
    change_for: Decimal | None = None

    def add(self, item: PizzaItem | DrinkItem) -> None:
        """Adds one unit, merging with an identical line already in the cart."""
        product = item.model_dump(exclude={"quantity"})
        for existing in self.items:
            if existing.model_dump(exclude={"quantity"}) == product:
                existing.quantity += 1
                return
        self.items.append(item)

    def remove_one(self, item: PizzaItem | DrinkItem) -> None:
        item.quantity -= 1
        if item.quantity <= 0:
            self.items.remove(item)

    def checkout(self) -> Checkout | None:
        if self.name is None or self.fulfillment is None or self.payment is None:
            return None
        return Checkout(
            name=self.name,
            fulfillment=self.fulfillment,
            address=self.address,
            payment=self.payment,
            change_for=self.change_for,
        )


class QuoteLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    description: str
    quantity: int
    unit_price: Decimal
    size_id: int | None = None
    flavor_id: int | None = None
    second_flavor_id: int | None = None
    drink_id: int | None = None

    @property
    def total(self) -> Decimal:
        return self.unit_price * self.quantity


class Quote(BaseModel):
    """A draft priced against the current menu. Lines keep the cart order."""

    model_config = ConfigDict(frozen=True)

    lines: list[QuoteLine]
    delivery_fee: Decimal

    @property
    def subtotal(self) -> Decimal:
        return sum((line.total for line in self.lines), Decimal("0"))

    @property
    def total(self) -> Decimal:
        return self.subtotal + self.delivery_fee


class MenuFlavor(BaseModel):
    name: str
    description: str | None
    # (size name, price) for each size the flavor is sold in.
    prices: list[tuple[str, Decimal]]


class MenuSection(BaseModel):
    name: str
    flavors: list[MenuFlavor]
