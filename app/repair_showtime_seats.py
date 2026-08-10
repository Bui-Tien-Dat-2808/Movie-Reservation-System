import asyncio
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload
from app.db.session import AsyncSessionLocal
from app.models.showtime import Showtime, ShowtimeStatus
from app.models.showtime_seat import ShowtimeSeat, SeatStatus
from app.models.room import Room

async def repair_all_showtime_seats():
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(Showtime)
            .where(Showtime.status != ShowtimeStatus.CANCELLED)
            .options(selectinload(Showtime.room).selectinload(Room.seats), selectinload(Showtime.showtime_seats))
        )
        showtimes = res.scalars().all()
        print(f"Repairing showtime_seats for {len(showtimes)} active showtimes...")

        repaired_count = 0
        for idx, st in enumerate(showtimes, 1):
            if not st.showtime_seats and st.room and st.room.seats:
                for seat in st.room.seats:
                    if seat.is_active:
                        db.add(ShowtimeSeat(
                            showtime_id=st.id,
                            seat_id=seat.id,
                            status=SeatStatus.AVAILABLE,
                        ))
                repaired_count += 1
                if idx % 100 == 0:
                    await db.commit()
                    print(f"Repaired {idx}/{len(showtimes)} showtimes...")

        await db.commit()
        print(f"Successfully repaired {repaired_count} showtimes!")

if __name__ == "__main__":
    asyncio.run(repair_all_showtime_seats())
