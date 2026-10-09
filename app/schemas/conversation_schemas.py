from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.models import Fulfillment, PaymentMethod


class Step(StrEnum):
    MAIN_MENU = "main_menu"
    PIZZA_CATEGORY = "pizza_category"
    PIZZA_SIZE = "pizza_size"
    PIZZA_FLAVOR = "pizza_flavor"
    CART = "cart"
    CART_REMOVE = "cart_remove"
    DRINK = "drink"
    NAME = "name"
    FULFILLMENT = "fulfillment"
    ADDRESS = "address"
    PAYMENT = "payment"
    CHANGE = "change"
    CHANGE_AMOUNT = "change_amount"
    CONFIRM = "confirm"
    HANDOFF = "handoff"


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


class Checkout(BaseModel):
    """Checkout answers, once all of them are known."""

    name: str
    fulfillment: Fulfillment
    address: str | None
    payment: PaymentMethod
    change_for: Decimal | None


class Draft(BaseModel):
    """In-progress order, stored as JSON on the conversation. It holds ids only: prices always come from the menu."""

    items: list[CartItem] = []
    pending: PendingPizza = PendingPizza()
    page: int = 0
    name: str | None = None
    fulfillment: Fulfillment | None = None
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
