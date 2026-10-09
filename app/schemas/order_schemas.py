from decimal import Decimal

from pydantic import BaseModel, ConfigDict


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
