import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .base import Base, pg_enum


class Fulfillment(enum.StrEnum):
    PICKUP = "pickup"
    DELIVERY = "delivery"


class PaymentMethod(enum.StrEnum):
    CASH = "cash"
    CARD = "card"
    PIX = "pix"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), index=True)
    customer_name: Mapped[str] = mapped_column(String(80))
    fulfillment: Mapped[Fulfillment] = mapped_column(pg_enum(Fulfillment, "fulfillment"))
    address: Mapped[str | None] = mapped_column(Text)
    payment_method: Mapped[PaymentMethod] = mapped_column(pg_enum(PaymentMethod, "payment_method"))
    # Banknote value the customer will pay with, when change is needed.
    change_for: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    items: Mapped[list["OrderItem"]] = relationship(cascade="all, delete-orphan")


class OrderItem(Base):
    """Description and price are snapshots, so later menu edits never rewrite past orders."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    description: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(SmallInteger)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    pizza_size_id: Mapped[int | None] = mapped_column(ForeignKey("pizza_sizes.id", ondelete="SET NULL"))
    flavor_id: Mapped[int | None] = mapped_column(ForeignKey("pizza_flavors.id", ondelete="SET NULL"))
    second_flavor_id: Mapped[int | None] = mapped_column(ForeignKey("pizza_flavors.id", ondelete="SET NULL"))
    drink_id: Mapped[int | None] = mapped_column(ForeignKey("drinks.id", ondelete="SET NULL"))
