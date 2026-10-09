from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer


class CustomerRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create(self, jid: str) -> Customer:
        customer = (await self.db.execute(select(Customer).where(Customer.jid == jid))).scalar_one_or_none()
        if customer is None:
            customer = Customer(jid=jid)
            self.db.add(customer)
            await self.db.flush()
        return customer
