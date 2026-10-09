import enum

from sqlalchemy import Enum
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def pg_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    """Native PostgreSQL enum that stores member values instead of the Python names."""
    return Enum(enum_cls, name=name, values_callable=lambda members: [member.value for member in members])
