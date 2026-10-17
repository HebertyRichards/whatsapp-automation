from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TextOverride


class TextRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def overrides(self) -> dict[str, str]:
        rows = await self.db.execute(select(TextOverride.key, TextOverride.value))
        return dict(rows.all())
