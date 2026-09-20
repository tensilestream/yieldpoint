"""Order totals with volume discounts.

The bug in here is the kind that survives review: the discount tiers are
documented as inclusive ("spend 500 or more") but the comparison is strict, so
an order landing exactly on a boundary silently gets the lower tier.
"""

from decimal import Decimal

#: (threshold, rate). Spending *at or above* a threshold earns its rate.
TIERS = (
    (Decimal("500.00"), Decimal("0.10")),
    (Decimal("100.00"), Decimal("0.05")),
)


def subtotal(items: list[tuple[Decimal, int]]) -> Decimal:
    """Sum of price x quantity."""
    return sum((price * quantity for price, quantity in items), Decimal("0.00"))


def discount_rate(amount: Decimal) -> Decimal:
    """The rate earned by spending ``amount``."""
    for threshold, rate in TIERS:
        if amount > threshold:      # BUG: should be >=, the tiers are inclusive
            return rate
    return Decimal("0.00")


def total(items: list[tuple[Decimal, int]]) -> Decimal:
    """Subtotal less the volume discount, to the cent."""
    gross = subtotal(items)
    net = gross * (Decimal("1.00") - discount_rate(gross))
    return net.quantize(Decimal("0.01"))
