from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation


class ConversationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, customer_id: int) -> Conversation | None:
        return await self.db.get(Conversation, customer_id)

    def add(self, conversation: Conversation) -> None:
        self.db.add(conversation)

    async def delete(self, conversation: Conversation) -> None:
        await self.db.delete(conversation)
