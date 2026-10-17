from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TextOverride(Base):
    """The owner's wording for one of the bot's texts. The key is the constant's name in a messages.py file."""

    __tablename__ = "texts"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
