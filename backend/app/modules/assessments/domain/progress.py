"""Pure assessment arithmetic: rounding a measured value to its field, and the summary of one field's history
(FIT-02, FIT-03, FIT-05). No I/O."""

from decimal import ROUND_HALF_UP, Decimal


def rounded(value: Decimal, decimal_places: int) -> Decimal:
    """Half-up to the field's decimal places, once, on write (data-model-people 5.4)."""
    return Decimal(value).quantize(Decimal(1).scaleb(-decimal_places), rounding=ROUND_HALF_UP)


def best(values: list[Decimal], direction: str) -> Decimal | None:
    """The personal best: highest or lowest by the field's direction; none when the field has no direction."""
    if not values or direction == "none":
        return None
    return max(values) if direction == "higher" else min(values)


def summary(points: list[tuple[object, Decimal]], direction: str) -> dict:
    """Latest, first, change and best of a series given newest first as (when, value) pairs."""
    if not points:
        return {"latest_value": None, "first_value": None, "change": None, "best_value": None}
    latest, first = points[0][1], points[-1][1]
    return {"latest_value": latest, "first_value": first, "change": latest - first,
            "best_value": best([v for _, v in points], direction)}  # fmt: skip
