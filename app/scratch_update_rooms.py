import asyncio
from sqlalchemy import text, select
from app.db.session import AsyncSessionLocal
from app.models.room import Room
from app.models.seat import Seat
from app.api.v1.rooms import _generate_seats

async def update_all_rooms():
    async with AsyncSessionLocal() as db:
        # Add 'KIDS' and 'kids' to seattype enum in postgresql
        try:
            await db.execute(text("ALTER TYPE seattype ADD VALUE IF NOT EXISTS 'KIDS'"))
            await db.commit()
            print("Enum seattype updated with KIDS value.")
        except Exception as e:
            print("Enum update note:", e)
            await db.rollback()

        res = await db.execute(select(Room))
        all_rooms = res.scalars().all()
        print("Total rooms to re-layout:", len(all_rooms))

        for r in all_rooms:
            # Delete existing seats
            await db.execute(text(f"DELETE FROM seats WHERE room_id = {r.id}"))
            await db.flush()
            # Regenerate seats using new realistic cinema logic
            await _generate_seats(db, r)
            print(f"Regenerated seats for {r.name} ({r.room_type}) successfully.")

        await db.commit()
        print("All room layouts updated successfully in database!")

if __name__ == "__main__":
    asyncio.run(update_all_rooms())
