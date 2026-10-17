from datetime import time

from sqlalchemy import CheckConstraint, SmallInteger, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class StoreSettings(Base):
    """Single row (id is always 1) with what the owner tunes without a deploy. Modules keep their own settings."""

    __tablename__ = "store_settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_store_settings_single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(80))
    timezone: Mapped[str] = mapped_column(String(64), server_default="America/Sao_Paulo")
    business_type: Mapped[str] = mapped_column(String(32))
    staff_jid: Mapped[str | None] = mapped_column(String(64))


class OpeningHours(Base):
    """One shift per weekday. A closing time at or before the opening time ends on the next day."""

    __tablename__ = "opening_hours"
    __table_args__ = (CheckConstraint("weekday BETWEEN 1 AND 7", name="ck_opening_hours_weekday"),)

    # ISO weekday: 1 = Monday ... 7 = Sunday.
    weekday: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    opens_at: Mapped[time] = mapped_column(Time)
    closes_at: Mapped[time] = mapped_column(Time)
