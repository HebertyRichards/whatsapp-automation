from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Conversation(Base):
    """Where a customer is in the flow. No row (or a stale `updated_at`) means no open session."""

    __tablename__ = "conversations"

    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True)
    # Plain string, not a PG enum: steps change with the code and should not need a migration.
    step: Mapped[str] = mapped_column(String(32))
    draft: Mapped[dict[str, object]] = mapped_column(JSONB)
    invalid_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
