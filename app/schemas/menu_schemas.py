from decimal import Decimal

from pydantic import BaseModel


class MenuFlavor(BaseModel):
    name: str
    description: str | None
    # (size name, price) for each size the flavor is sold in.
    prices: list[tuple[str, Decimal]]


class MenuSection(BaseModel):
    name: str
    flavors: list[MenuFlavor]
