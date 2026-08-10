from decimal import Decimal
from typing import List, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.concession import Concession, ReservationConcession
from app.schemas.concession import ConcessionCreate, ConcessionOrderItem, ConcessionUpdate

logger = structlog.get_logger()

DEFAULT_CONCESSIONS = [
    {
        "name": "Combo Solo",
        "description": "1 Bắp rang cỡ vừa + 1 Nước ngọt cỡ vừa",
        "price": Decimal("85000.00"),
        "category": "combo",
        "size": "M",
        "image_url": "https://images.unsplash.com/photo-1578849278619-e73505e9610f?w=500",
        "is_active": True,
    },
    {
        "name": "Combo Couple",
        "description": "1 Bắp rang cỡ lớn + 2 Nước ngọt cỡ vừa",
        "price": Decimal("125000.00"),
        "category": "combo",
        "size": "L",
        "image_url": "https://images.unsplash.com/photo-1585647347384-2593bc35786b?w=500",
        "is_active": True,
    },
    {
        "name": "Combo Family",
        "description": "2 Bắp rang lớn + 4 Nước ngọt + 1 Snack bắp",
        "price": Decimal("210000.00"),
        "category": "combo",
        "size": "XL",
        "image_url": "https://images.unsplash.com/photo-1578849278619-e73505e9610f?w=500",
        "is_active": True,
    },
    {
        "name": "Bắp Rang Bơ (S)",
        "description": "Bắp rang vị bơ thơm lừng cỡ nhỏ",
        "price": Decimal("45000.00"),
        "category": "popcorn",
        "size": "S",
        "image_url": "https://images.unsplash.com/photo-1578849278619-e73505e9610f?w=500",
        "is_active": True,
    },
    {
        "name": "Bắp Rang Bơ (M)",
        "description": "Bắp rang vị bơ thơm lừng cỡ vừa",
        "price": Decimal("55000.00"),
        "category": "popcorn",
        "size": "M",
        "image_url": "https://images.unsplash.com/photo-1578849278619-e73505e9610f?w=500",
        "is_active": True,
    },
    {
        "name": "Bắp Rang Phô Mai (L)",
        "description": "Bắp rang vị phô Mai đậm đà cỡ lớn",
        "price": Decimal("65000.00"),
        "category": "popcorn",
        "size": "L",
        "image_url": "https://images.unsplash.com/photo-1578849278619-e73505e9610f?w=500",
        "is_active": True,
    },
    {
        "name": "Coca Cola (M)",
        "description": "Nước ngọt Coca Cola mát lạnh cỡ vừa",
        "price": Decimal("32000.00"),
        "category": "drink",
        "size": "M",
        "image_url": "https://images.unsplash.com/photo-1622483767028-3f66f32aef97?w=500",
        "is_active": True,
    },
    {
        "name": "Pepsi (L)",
        "description": "Nước ngọt Pepsi mát lạnh cỡ lớn",
        "price": Decimal("38000.00"),
        "category": "drink",
        "size": "L",
        "image_url": "https://images.unsplash.com/photo-1622483767028-3f66f32aef97?w=500",
        "is_active": True,
    },
    {
        "name": "Snack Khoai Tây Lay's",
        "description": "Bánh snack khoai tây vị tự nhiên",
        "price": Decimal("25000.00"),
        "category": "snack",
        "size": None,
        "image_url": "https://images.unsplash.com/photo-1566478989037-eec170784d0b?w=500",
        "is_active": True,
    },
    {
        "name": "Xúc Xích Đức Nướng",
        "description": "Xúc xích Đức thơm ngon kèm sốt mù tạt",
        "price": Decimal("35000.00"),
        "category": "food",
        "size": None,
        "image_url": "https://images.unsplash.com/photo-1541745537411-b8046dc6d66c?w=500",
        "is_active": True,
    },
]


class ConcessionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_concessions(self, active_only: bool = True) -> List[Concession]:
        query = select(Concession)
        if active_only:
            query = query.where(Concession.is_active.is_(True))
        query = query.order_by(Concession.category, Concession.id)
        result = await self.db.execute(query)
        items = list(result.scalars().all())

        if not items:
            logger.info("No concessions found, seeding default concessions...")
            for data in DEFAULT_CONCESSIONS:
                c = Concession(**data)
                self.db.add(c)
            await self.db.commit()
            result = await self.db.execute(query)
            items = list(result.scalars().all())

        return items

    async def create_concession(self, data: ConcessionCreate) -> Concession:
        c = Concession(
            name=data.name,
            description=data.description,
            price=data.price,
            category=data.category,
            size=data.size,
            image_url=data.image_url,
            is_active=data.is_active,
        )
        self.db.add(c)
        await self.db.commit()
        await self.db.refresh(c)
        return c

    async def update_concession(self, concession_id: int, data: ConcessionUpdate) -> Concession:
        res = await self.db.execute(select(Concession).where(Concession.id == concession_id))
        c = res.scalar_one_or_none()
        if not c:
            raise ValueError(f"Concession {concession_id} not found")

        update_dict = data.model_dump(exclude_unset=True)
        for key, val in update_dict.items():
            setattr(c, key, val)

        await self.db.commit()
        await self.db.refresh(c)
        return c

    async def process_concession_orders(
        self, reservation_id: int, orders: List[ConcessionOrderItem]
    ) -> Decimal:
        total_cost = Decimal("0.00")
        if not orders:
            return total_cost

        for order in orders:
            res = await self.db.execute(
                select(Concession).where(Concession.id == order.concession_id)
            )
            c = res.scalar_one_or_none()
            if not c:
                continue

            cost = c.price * Decimal(str(order.quantity))
            total_cost += cost

            rc = ReservationConcession(
                reservation_id=reservation_id,
                concession_id=c.id,
                quantity=order.quantity,
                unit_price=c.price,
            )
            self.db.add(rc)

        await self.db.flush()
        return total_cost
