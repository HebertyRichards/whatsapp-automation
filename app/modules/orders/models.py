import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base, pg_enum


class HalfHalfPricing(enum.StrEnum):
    HIGHEST = "highest"
    AVERAGE = "average"


class Fulfillment(enum.StrEnum):
    PICKUP = "pickup"
    DELIVERY = "delivery"


class PaymentMethod(enum.StrEnum):
    CASH = "cash"
    CARD = "card"
    PIX = "pix"


class OrderSettings(Base):
    """Single row (id is always 1) with the order rules the owner tunes without a deploy."""

    __tablename__ = "order_settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_order_settings_single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    half_half_pricing: Mapped[HalfHalfPricing] = mapped_column(
        pg_enum(HalfHalfPricing, "half_half_pricing"),
        server_default=HalfHalfPricing.HIGHEST.value,
    )


class PizzaCategory(Base):
    __tablename__ = "pizza_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(server_default=true())


class PizzaSize(Base):
    __tablename__ = "pizza_sizes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    # Whether the size can be ordered with two flavors.
    allows_half: Mapped[bool] = mapped_column(server_default=true())
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(server_default=true())


class PizzaFlavor(Base):
    __tablename__ = "pizza_flavors"
    __table_args__ = (UniqueConstraint("category_id", "name", name="uq_pizza_flavors_category_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("pizza_categories.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(server_default=true())


class PizzaPrice(Base):
    """A flavor is only offered in the sizes it has a price for."""

    __tablename__ = "pizza_prices"
    __table_args__ = (CheckConstraint("price >= 0", name="ck_pizza_prices_price"),)

    flavor_id: Mapped[int] = mapped_column(ForeignKey("pizza_flavors.id", ondelete="CASCADE"), primary_key=True)
    size_id: Mapped[int] = mapped_column(ForeignKey("pizza_sizes.id", ondelete="CASCADE"), primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))


class Drink(Base):
    __tablename__ = "drinks"
    __table_args__ = (CheckConstraint("price >= 0", name="ck_drinks_price"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_active: Mapped[bool] = mapped_column(server_default=true())


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
