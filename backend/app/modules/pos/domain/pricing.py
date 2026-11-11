"""Cart arithmetic (POS-09, POS-10): pure functions over integer minor units.

Discounts apply in sequence, each to what is left of its target lines after the earlier ones; a percentage
is rounded half-up once on that base and a flat amount is capped at it. Every discount is shared over its
target lines by largest remainder in proportion to their remaining nets, so the shares sum to the discount
exactly (the reference's 2025-04-09 rounding fix). Taxes are the caller's: they apply to each line's final net.
"""

from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


def round_half_up(amount: Decimal) -> int:
    return int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def split_by_weight(total: int, weights: Sequence[int]) -> list[int]:
    """`total` shared in proportion to `weights` by largest remainder; ties go to the earlier weight."""
    whole = sum(weights)
    if whole <= 0:
        return [0] * len(weights)
    shares = [total * weight // whole for weight in weights]
    by_remainder = sorted(range(len(weights)), key=lambda i: (-(total * weights[i] % whole), i))
    for index in by_remainder[: total - sum(shares)]:
        shares[index] += 1
    return shares


@dataclass(frozen=True)
class Discount:
    key: Hashable
    pct: Decimal | None = None
    minor: int | None = None
    line_keys: tuple[Hashable, ...] | None = None  # None: the whole sale


@dataclass
class Applied:
    applied: dict[Hashable, int]  # discount key -> amount actually taken
    shares: dict[tuple[Hashable, Hashable], int]  # (discount key, line key) -> share, zero shares omitted
    nets: dict[Hashable, int]  # line key -> net after every discount


def apply_discounts(gross: dict[Hashable, int], discounts: Sequence[Discount]) -> Applied:
    nets = dict(gross)
    result = Applied(applied={}, shares={}, nets=nets)
    for discount in discounts:
        keys = [k for k in (discount.line_keys if discount.line_keys is not None else nets) if k in nets]
        base = sum(nets[k] for k in keys)
        if discount.pct is not None:
            amount = round_half_up(Decimal(base) * discount.pct / 100)
        else:
            amount = discount.minor or 0
        amount = max(0, min(amount, base))
        result.applied[discount.key] = amount
        for key, share in zip(keys, split_by_weight(amount, [nets[k] for k in keys]), strict=True):
            if share:
                result.shares[(discount.key, key)] = share
                nets[key] -= share
    return result


def prorate(total: int, quantity: int, already: int, taking: int) -> int:
    """The part of a line total that `taking` more units carry once `already` were taken: cumulative rounding,
    so returning every unit, in any number of steps, gives back exactly the line total."""
    return round_half_up(Decimal(total) * (already + taking) / quantity) - round_half_up(
        Decimal(total) * already / quantity
    )
