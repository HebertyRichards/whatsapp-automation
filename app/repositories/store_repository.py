from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OpeningHours, StoreSettings


class StoreRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_settings(self) -> StoreSettings | None:
        return await self.db.get(StoreSettings, 1)

    async def list_opening_hours(self) -> list[OpeningHours]:
        return list((await self.db.execute(select(OpeningHours))).scalars().all())
