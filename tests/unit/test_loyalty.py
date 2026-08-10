from app.services.loyalty_service import LoyaltyService


def test_calculate_tier_for_bronze_and_diamond():
    assert LoyaltyService.calculate_tier(0) == "bronze"
    assert LoyaltyService.calculate_tier(999) == "bronze"
    assert LoyaltyService.calculate_tier(1000) == "silver"
    assert LoyaltyService.calculate_tier(5000) == "gold"
    assert LoyaltyService.calculate_tier(10000) == "diamond"


def test_points_to_next_tier():
    assert LoyaltyService.points_to_next_tier(950) == 50
    assert LoyaltyService.points_to_next_tier(1000) == 4000
    assert LoyaltyService.points_to_next_tier(4999) == 1
    assert LoyaltyService.points_to_next_tier(5000) == 5000
