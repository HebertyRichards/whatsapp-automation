from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, SmallInteger, String, Text, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


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
