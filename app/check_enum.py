import asyncio
from sqlalchemy import text
from app.db.session import AsyncSessionLocal

async def check_enum():
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("SELECT enumlabel FROM pg_enum JOIN pg_type ON pg_enum.enumtypid = pg_type.oid WHERE pg_type.typname = 'seattype'"))
        print("PostgreSQL seattype values:", res.scalars().all())

if __name__ == "__main__":
    asyncio.run(check_enum())
