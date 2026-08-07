from decimal import Decimal
from typing import List, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.concession import Concession, ReservationConcession
from app.schemas.concession import ConcessionCreate, ConcessionUpdate, ConcessionOrderItem

logger = structlog.get_logger()


# Default combo items to seed on first startup
DEFAULT_CONCESSIONS = [
    {
        "name": "Combo Đôi Bắp + 2 Nước",
        "description": "1 bắp rang bơ cỡ lớn và 2 ly nước ngọt cỡ vừa",
        "price": Decimal("95000"),
        "category": "combo",
        "image_url": "https://images.unsplash.com/photo-1585647347483-22b66260dfff?w=400&q=80",
    },
    {
        "name": "Combo 1 Bắp Cỡ Lớn",
        "description": "Bắp rang bơ thơm ngậy cỡ đại, đủ ăn cho 2 người",
        "price": Decimal("55000"),
        "category": "popcorn",
        "image_url": "https://images.unsplash.com/photo-1578849278619-e73505e9610f?w=400&q=80",
    },
    {
        "name": "Bắp Cỡ Vừa",
        "description": "Bắp rang bơ vị mặn ngọt đặc trưng của rạp cỡ trung",
        "price": Decimal("40000"),
        "category": "popcorn",
        "image_url": "https://images.unsplash.com/photo-1526736279569-e5f5a10001fb?w=400&q=80",
    },
    {
        "name": "Nước Ngọt Cỡ Lớn",
        "description": "Coca-Cola / Pepsi / Sprite cỡ XL có đá lạnh",
        "price": Decimal("35000"),
        "category": "drink",
        "image_url": "https://images.unsplash.com/photo-1622483767028-3f66f32aef97?w=400&q=80",
    },
    {
        "name": "Combo Gia Đình 4 Người",
        "description": "2 bắp cỡ lớn + 4 nước ngọt. Tiết kiệm 30% so với mua lẻ",
        "price": Decimal("180000"),
        "category": "combo",
        "image_url": "https://images.unsplash.com/photo-1627989580309-bfaf3e58af6f?w=400&q=80",
    },
    {
        "name": "Bắp Rang Ngọt Vị Caramel",
        "description": "Bắp caramel vàng giòn, ngọt nhẹ, đậm đà vị bơ",
        "price": Decimal("60000"),
        "category": "popcorn",
        "image_url": "https://images.unsplash.com/photo-1556909114-f6e7ad7d3136?w=400&q=80",
    },
]


class ConcessionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all_active(self) -> List[Concession]:
        result = await self.db.execute(
            select(Concession).where(Concession.is_active == True).order_by(Concession.id)
        )
        return result.scalars().all()

    async def get_all(self) -> List[Concession]:
        result = await self.db.execute(
            select(Concession).order_by(Concession.id)
        )
        return result.scalars().all()

    async def get_by_id(self, concession_id: int) -> Optional[Concession]:
        result = await self.db.execute(
            select(Concession).where(Concession.id == concession_id)
        )
        return result.scalar_one_or_none()

    async def create(self, data: ConcessionCreate) -> Concession:
        concession = Concession(
            name=data.name,
            description=data.description,
            price=data.price,
            category=data.category,
            size=data.size,
            image_url=data.image_url,
            is_active=data.is_active,
        )
        self.db.add(concession)
        await self.db.commit()
        await self.db.refresh(concession)
        return concession

    async def update(self, concession_id: int, data: ConcessionUpdate) -> Optional[Concession]:
        concession = await self.get_by_id(concession_id)
        if not concession:
            return None
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(concession, field, value)
        await self.db.commit()
        await self.db.refresh(concession)
        return concession

    async def process_concession_orders(
        self,
        reservation_id: int,
        orders: List[ConcessionOrderItem],
    ) -> Decimal:
        """Add concession items to a reservation. Returns total concession cost."""
        concession_total = Decimal("0.00")
        for item in orders:
            concession = await self.get_by_id(item.concession_id)
            if not concession or not concession.is_active:
                continue
            rc = ReservationConcession(
                reservation_id=reservation_id,
                concession_id=item.concession_id,
                quantity=item.quantity,
                unit_price=concession.price,
            )
            self.db.add(rc)
            concession_total += concession.price * item.quantity
        return concession_total

    @classmethod
    async def seed_defaults(cls, db: AsyncSession) -> None:
        """Seed default concession items if none exist."""
        result = await db.execute(select(Concession))
        existing = result.scalars().first()
        if existing:
            logger.info("Concessions already seeded in database")
            return
        concessions = [
            Concession(
                name=c["name"],
                description=c["description"],
                price=c["price"],
                category=c["category"],
                image_url=c["image_url"],
                is_active=True,
            )
            for c in DEFAULT_CONCESSIONS
        ]
        db.add_all(concessions)
        await db.commit()
        logger.info("Default concessions seeded", count=len(concessions))
