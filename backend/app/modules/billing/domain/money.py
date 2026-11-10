"""Money arithmetic (overview 3.6): integer minor units, Decimal in between, half-up rounding once at the line."""

from decimal import ROUND_HALF_UP, Decimal


def round_half_up(amount: Decimal) -> int:
    """Half away from zero, so a negated amount rounds to the negation of the rounded amount."""
    return int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def net_amount(quantity: Decimal, unit_price_minor: int, discount_minor: int = 0) -> int:
    """quantity times unit price, rounded, minus the (already rounded) discount."""
    return round_half_up(quantity * unit_price_minor) - discount_minor


def tax_amount(net_minor: int, rate: Decimal) -> int:
    """One tax on the discounted net: non-compounding, tax-exclusive, rounded per tax per line (ADR 0003 s10)."""
    return round_half_up(net_minor * rate)
