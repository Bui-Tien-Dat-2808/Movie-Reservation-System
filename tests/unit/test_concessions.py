import pytest
from decimal import Decimal
from pydantic import ValidationError

from app.schemas.concession import ConcessionCreate, ConcessionUpdate, ConcessionResponse


def test_concession_create_schema_valid():
    concession = ConcessionCreate(
        name="Combo Solo",
        category="combo",
        price=Decimal("89000"),
        description="1 Bắp Ngọt (L) + 1 Nước Có Gas (L)",
        image_url="https://images.unsplash.com/photo-1578849278619-e73505e9610f",
        is_active=True
    )
    assert concession.name == "Combo Solo"
    assert concession.price == Decimal("89000")
    assert concession.category == "combo"


def test_concession_create_schema_invalid_price():
    with pytest.raises(ValidationError):
        ConcessionCreate(
            name="Combo Negative",
            category="combo",
            price=Decimal("-50000"),
            is_active=True
        )


def test_concession_update_partial():
    update_data = ConcessionUpdate(
        price=Decimal("95000"),
        is_active=False
    )
    assert update_data.name is None
    assert update_data.price == Decimal("95000")
    assert update_data.is_active is False
