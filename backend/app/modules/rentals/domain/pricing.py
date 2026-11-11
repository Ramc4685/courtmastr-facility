"""The rental pricing function (data-model-core 5.1, RNT-02): pure, deterministic, no database.

1. Unit price = the member price when the payer is an active member and it is set, else the rate amount.
2. `per_hour` occurrences are cut into segments at every rule's time band and at local midnight; the other
   bases are one segment per occurrence (`flat`: one for the whole request). In each segment the first matching
   `rate` rule by sort_order replaces the unit price; every matching `discount` rule adds its per-unit discount.
   A band matches a whole-occurrence segment when the occurrence starts inside it.
3. Quantity: `per_hour` = minutes / 60; `per_occurrence` = 1; `flat` = 1. `per_resource` multiplies by the
   number of resources, `once` does not.
4. Segments are grouped into lines by `line_grouping`, then by unit price (a line never mixes prices).
5. Each line's quantity is rounded to 2 places, its amount half-up once; occurrence shares of a line are a
   largest-remainder split, so cancelling one occurrence can give back exactly its part.

Times are aware datetimes in the location's zone, so a band such as 17:00-22:00 means local wall time on that
day and minutes are real elapsed minutes across a clock change.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

CENT = Decimal("0.01")


def half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Rule:
    id: UUID | None
    kind: str  # rate | discount
    name: str = ""
    sort_order: int = 0
    start_time: time | None = None
    end_time: time | None = None  # None with a start_time = the band runs to midnight (stored as 24:00)
    starts_on: date | None = None
    ends_on: date | None = None
    weekdays: tuple[int, ...] | None = None
    membership_type_id: UUID | None = None
    amount_minor: int | None = None
    discount_pct: Decimal | None = None
    discount_minor: int | None = None


@dataclass(frozen=True)
class Rate:
    id: UUID | None
    name: str
    amount_minor: int
    basis: str  # per_hour | per_occurrence | flat
    member_amount_minor: int | None = None
    multi_resource_mode: str = "per_resource"
    line_grouping: str = "combined"
    rules: tuple[Rule, ...] = ()


@dataclass(frozen=True)
class Occurrence:
    index: int
    starts_at: datetime  # aware, location zone
    ends_at: datetime
    resource_ids: tuple[UUID, ...]


@dataclass
class Line:
    description: str
    rental_rate_id: UUID | None
    basis: str
    quantity: Decimal
    unit_amount_minor: int
    discount_minor: int
    amount_minor: int
    resource_id: UUID | None
    occurrence_index: int | None
    applied_rule_id: UUID | None
    is_member_price: bool
    items: list[tuple[int, UUID | None, int]] = field(default_factory=list)  # (occurrence, resource, share)


@dataclass(frozen=True)
class _Segment:
    occurrence: int
    resource: UUID | None
    quantity: Decimal
    unit: int
    discount: Decimal  # per segment, unrounded
    rule: UUID | None


def _matches(rule: Rule, start: datetime, end: datetime, member_types: frozenset) -> bool:
    day = start.date()
    if rule.starts_on and day < rule.starts_on or rule.ends_on and day > rule.ends_on:
        return False
    if rule.weekdays and day.isoweekday() not in rule.weekdays:
        return False
    if rule.membership_type_id is not None and rule.membership_type_id not in member_types:
        return False
    if rule.start_time is not None:
        local = start.timetz().replace(tzinfo=None)
        if local < rule.start_time or (rule.end_time is not None and local >= rule.end_time):
            return False
    return True


def _cuts(rules: tuple[Rule, ...], start: datetime, end: datetime) -> list[datetime]:
    """Segment boundaries of one per-hour occurrence: band edges and local midnights inside (start, end)."""
    zone = start.tzinfo
    points = {start, end}
    day = start.date()
    while day <= end.date():
        points.add(datetime.combine(day, time(0), zone))
        for rule in rules:
            if rule.start_time is not None:
                points.add(datetime.combine(day, rule.start_time, zone))
                if rule.end_time is not None:
                    points.add(datetime.combine(day, rule.end_time, zone))
        day += timedelta(days=1)
    return sorted(p for p in points if start <= p <= end)


def _segments(
    rate: Rate, occurrences: list[Occurrence], is_member: bool, member_types: frozenset
) -> tuple[list[_Segment], bool]:
    base = rate.member_amount_minor if is_member and rate.member_amount_minor is not None else rate.amount_minor
    rules = tuple(sorted(rate.rules, key=lambda r: r.sort_order))
    per_resource = rate.multi_resource_mode == "per_resource"

    def priced(start: datetime, end: datetime) -> tuple[int, Decimal, UUID | None]:
        unit, rule_id = base, None
        for rule in rules:
            if rule.kind == "rate" and _matches(rule, start, end, member_types):
                unit, rule_id = rule.amount_minor, rule.id
                break
        discount = Decimal(0)
        for rule in rules:
            if rule.kind == "discount" and _matches(rule, start, end, member_types):
                discount += (
                    Decimal(unit) * rule.discount_pct / 100 if rule.discount_pct is not None else rule.discount_minor
                )
        return unit, min(discount, Decimal(unit)), rule_id

    pieces: list[tuple[int, datetime, datetime, Decimal]] = []  # (occurrence, start, end, quantity)
    if rate.basis == "flat":
        first = occurrences[0]
        pieces.append((first.index, first.starts_at, first.ends_at, Decimal(1)))
    for occurrence in occurrences if rate.basis != "flat" else ():
        if rate.basis == "per_occurrence":
            pieces.append((occurrence.index, occurrence.starts_at, occurrence.ends_at, Decimal(1)))
            continue
        cuts = _cuts(rules, occurrence.starts_at, occurrence.ends_at)
        for start, end in zip(cuts, cuts[1:], strict=False):
            seconds = Decimal(int((end.astimezone(UTC) - start.astimezone(UTC)).total_seconds()))  # real time
            if seconds:
                pieces.append((occurrence.index, start, end, seconds / 3600))

    resources = {o.index: o.resource_ids for o in occurrences}
    segments = []
    for index, start, end, quantity in pieces:
        unit, discount, rule_id = priced(start, end)
        targets = resources[index] if per_resource else resources[index][:1]
        for resource in targets:
            segments.append(_Segment(index, resource, quantity, unit, discount * quantity, rule_id))
    return segments, base != rate.amount_minor


def _largest_remainder(total: int, weights: list[Decimal]) -> list[int]:
    whole = sum(weights)
    if total == 0 or whole == 0:
        return [0] * len(weights)
    raw = [total * w / whole for w in weights]
    shares = [int(r) for r in raw]
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - shares[i]), i))
    for i in order[: total - sum(shares)]:
        shares[i] += 1
    return shares


def price(
    rate: Rate,
    occurrences: list[Occurrence],
    *,
    is_member: bool = False,
    member_types: frozenset = frozenset(),
    grouping: str | None = None,
) -> list[Line]:
    """Price occurrences with one rate. `grouping` overrides the rate's line grouping (bill selected).
    `flat` produces one combined line whatever the grouping."""
    if not occurrences:
        return []
    occurrences = sorted(occurrences, key=lambda o: o.index)
    grouping = "combined" if rate.basis == "flat" else grouping or rate.line_grouping
    segments, member_priced = _segments(rate, occurrences, is_member, member_types)
    by_resource = grouping in ("per_resource", "per_resource_occurrence")
    by_occurrence = grouping in ("per_occurrence", "per_resource_occurrence")
    groups: dict[tuple, list[_Segment]] = defaultdict(list)
    for seg in segments:
        key = (seg.resource if by_resource else None, seg.occurrence if by_occurrence else None, seg.unit)
        groups[key].append(seg)
    lines = []
    for (resource, occurrence, unit), segs in groups.items():
        quantity = sum((s.quantity for s in segs), Decimal(0)).quantize(CENT, rounding=ROUND_HALF_UP)
        gross = half_up(quantity * unit)
        discount = min(half_up(sum((s.discount for s in segs), Decimal(0))), gross)
        amount = gross - discount
        weights: dict[tuple, Decimal] = defaultdict(Decimal)
        for s in segs:
            weights[
                (s.occurrence, s.resource if by_resource or rate.multi_resource_mode == "per_resource" else None)
            ] += s.quantity * s.unit - s.discount
        if rate.basis == "flat":  # one charge for the whole request: every occurrence carries a share
            weights = {(o.index, None): Decimal(1) for o in occurrences}
        keys = sorted(weights, key=lambda k: (k[0], str(k[1])))
        shares = _largest_remainder(amount, [weights[k] for k in keys])
        rules = {s.rule for s in segs}
        lines.append(
            Line(
                description=rate.name,
                rental_rate_id=rate.id,
                basis=rate.basis,
                quantity=quantity,
                unit_amount_minor=unit,
                discount_minor=discount,
                amount_minor=amount,
                resource_id=resource,
                occurrence_index=occurrence,
                applied_rule_id=rules.pop() if len(rules) == 1 else None,
                is_member_price=member_priced,
                items=[(k[0], k[1], share) for k, share in zip(keys, shares, strict=True)],
            )  # fmt: skip
        )
    lines.sort(key=lambda line: (line.occurrence_index or 0, str(line.resource_id or ""), -line.unit_amount_minor))
    return lines


def apply_discount(lines: list[Line], discount_minor: int) -> None:
    """A desk discount on the whole decision, taken from the lines in order until spent; shares follow."""
    left = discount_minor
    for line in lines:
        take = min(left, line.amount_minor)
        if take:
            line.discount_minor += take
            line.amount_minor -= take
            shares = _largest_remainder(line.amount_minor, [Decimal(share) for _, _, share in line.items])
            line.items = [(o, r, s) for (o, r, _), s in zip(line.items, shares, strict=True)]
            left -= take
    if left:
        raise ValueError("discount exceeds the total")


def tax_of(amount_minor: int, rates: list[Decimal]) -> int:
    """Each tax computed on the net and rounded half-up on its own, as billing posts it."""
    return sum(half_up(Decimal(amount_minor) * rate) for rate in rates)


def deposit_of(total_minor: int, pct: Decimal | None) -> int:
    return half_up(Decimal(total_minor) * pct / 100) if pct else 0
