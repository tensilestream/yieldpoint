from decimal import Decimal

from cart import discount_rate, subtotal, total


def test_subtotal_multiplies_price_by_quantity():
    assert subtotal([(Decimal("25.00"), 4)]) == Decimal("100.00")


def test_an_order_on_the_tier_boundary_earns_that_tier():
    """Spending exactly 500 earns the 10% tier: the tiers are inclusive."""
    assert discount_rate(Decimal("500.00")) == Decimal("0.10")
    assert total([(Decimal("250.00"), 2)]) == Decimal("450.00")


def test_an_order_below_every_tier_pays_full_price():
    assert total([(Decimal("10.00"), 2)]) == Decimal("20.00")
