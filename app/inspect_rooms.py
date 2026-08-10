import asyncio
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.db.session import AsyncSessionLocal
from app.models.room import Room

async def inspect_all_room_layouts():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Room).options(selectinload(Room.seats)))
        rooms = res.scalars().all()
        print("=== BÁO CÁO CẤU TRÚC SƠ ĐỒ GHẾ CÁC PHÒNG CHÍNH THỨC ===")
        for r in rooms:
            seats = r.seats
            reg = sum(1 for s in seats if (s.seat_type.value if hasattr(s.seat_type, 'value') else str(s.seat_type)).lower() in ('standard', 'regular'))
            vip = sum(1 for s in seats if (s.seat_type.value if hasattr(s.seat_type, 'value') else str(s.seat_type)).lower() == 'vip')
            cp = sum(1 for s in seats if (s.seat_type.value if hasattr(s.seat_type, 'value') else str(s.seat_type)).lower() == 'couple')
            kd = sum(1 for s in seats if (s.seat_type.value if hasattr(s.seat_type, 'value') else str(s.seat_type)).lower() == 'kids')
            print(f"* {r.name:<12} ({str(r.room_type.value if hasattr(r.room_type, 'value') else r.room_type).upper():<8}): {len(seats):>3} ghế -> Regular: {reg:>3}, VIP: {vip:>2}, Couple: {cp:>2}, Kids: {kd:>2}")

if __name__ == "__main__":
    asyncio.run(inspect_all_room_layouts())
