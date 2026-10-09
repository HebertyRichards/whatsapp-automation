from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order


class OrderRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def add(self, order: Order) -> Order:
        """Inserts the order and its items; flushed so the caller gets the generated id."""
        self.db.add(order)
        await self.db.flush()
        return order
