from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Drink, PizzaCategory, PizzaFlavor, PizzaPrice, PizzaSize


class MenuRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_categories(self) -> list[PizzaCategory]:
        """Active categories with at least one flavor that can actually be ordered."""
        offer = (
            select(PizzaPrice.flavor_id)
            .join(PizzaFlavor, PizzaFlavor.id == PizzaPrice.flavor_id)
            .join(PizzaSize, PizzaSize.id == PizzaPrice.size_id)
            .where(
                PizzaFlavor.category_id == PizzaCategory.id,
                PizzaFlavor.is_active,
                PizzaSize.is_active,
            )
        )
        stmt = (
            select(PizzaCategory)
            .where(PizzaCategory.is_active, offer.exists())
            .order_by(PizzaCategory.sort_order, PizzaCategory.name)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_sizes(self, category_id: int) -> list[PizzaSize]:
        """Active sizes in which the category has at least one priced flavor."""
        offer = (
            select(PizzaPrice.flavor_id)
            .join(PizzaFlavor, PizzaFlavor.id == PizzaPrice.flavor_id)
            .where(
                PizzaPrice.size_id == PizzaSize.id,
                PizzaFlavor.category_id == category_id,
                PizzaFlavor.is_active,
            )
        )
        stmt = (
            select(PizzaSize)
            .where(PizzaSize.is_active, offer.exists())
            .order_by(PizzaSize.sort_order, PizzaSize.name)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_flavors(self, category_id: int, size_id: int) -> list[tuple[PizzaFlavor, Decimal]]:
        """Flavors of the category priced for the size. The order defines the number the customer types."""
        stmt = (
            select(PizzaFlavor, PizzaPrice.price)
            .join(PizzaPrice, PizzaPrice.flavor_id == PizzaFlavor.id)
            .where(
                PizzaFlavor.category_id == category_id,
                PizzaFlavor.is_active,
                PizzaPrice.size_id == size_id,
            )
            .order_by(PizzaFlavor.sort_order, PizzaFlavor.name)
        )
        return [row._tuple() for row in (await self.db.execute(stmt)).all()]

    async def list_offers(self) -> list[tuple[str, PizzaFlavor, str, Decimal]]:
        """(category name, flavor, size name, price) for the whole active menu, in display order."""
        stmt = (
            select(PizzaCategory.name, PizzaFlavor, PizzaSize.name, PizzaPrice.price)
            .join(PizzaFlavor, PizzaFlavor.category_id == PizzaCategory.id)
            .join(PizzaPrice, PizzaPrice.flavor_id == PizzaFlavor.id)
            .join(PizzaSize, PizzaSize.id == PizzaPrice.size_id)
            .where(PizzaCategory.is_active, PizzaFlavor.is_active, PizzaSize.is_active)
            .order_by(
                PizzaCategory.sort_order,
                PizzaCategory.name,
                PizzaFlavor.sort_order,
                PizzaFlavor.name,
                PizzaSize.sort_order,
            )
        )
        return [row._tuple() for row in (await self.db.execute(stmt)).all()]

    async def list_drinks(self) -> list[Drink]:
        stmt = select(Drink).where(Drink.is_active).order_by(Drink.sort_order, Drink.name)
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_sizes(self, ids: set[int]) -> dict[int, PizzaSize]:
        return await self._by_id(PizzaSize, ids)

    async def get_flavors(self, ids: set[int]) -> dict[int, PizzaFlavor]:
        return await self._by_id(PizzaFlavor, ids)

    async def get_drinks(self, ids: set[int]) -> dict[int, Drink]:
        return await self._by_id(Drink, ids)

    async def get_prices(self, flavor_ids: set[int], size_ids: set[int]) -> dict[tuple[int, int], Decimal]:
        """Prices keyed by (flavor_id, size_id)."""
        if not flavor_ids or not size_ids:
            return {}
        stmt = select(PizzaPrice).where(PizzaPrice.flavor_id.in_(flavor_ids), PizzaPrice.size_id.in_(size_ids))
        return {(row.flavor_id, row.size_id): row.price for row in (await self.db.execute(stmt)).scalars()}

    async def _by_id[T: (PizzaSize, PizzaFlavor, Drink)](self, model: type[T], ids: set[int]) -> dict[int, T]:
        # Looked up regardless of is_active: an item already in a cart stays orderable.
        if not ids:
            return {}
        rows = (await self.db.execute(select(model).where(model.id.in_(ids)))).scalars()
        return {row.id: row for row in rows}
