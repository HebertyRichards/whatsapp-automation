import logging
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.models import HalfHalfPricing, Order, OrderSettings

logger = logging.getLogger(__name__)


class OrderRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._settings: OrderSettings | None = None

    async def add(self, order: Order) -> Order:
        """Inserts the order and its items; flushed so the caller gets the generated id."""
        self.db.add(order)
        await self.db.flush()
        return order

    async def settings(self) -> OrderSettings:
        """Read once per message. A missing row means free delivery, so orders still go through."""
        if self._settings is None:
            settings = await self.db.get(OrderSettings, 1)
            if settings is None:
                logger.error("order_settings is empty; run sql/orders.example.sql before using the bot")
                settings = OrderSettings(id=1, delivery_fee=Decimal("0"), half_half_pricing=HalfHalfPricing.HIGHEST)
            self._settings = settings
        return self._settings
