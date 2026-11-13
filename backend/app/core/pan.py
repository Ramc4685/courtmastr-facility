"""Card number (PAN) detector for stored free-text input (`app.core.schemas.In`, security-baseline section 3).

Favours precision, since refusing a legitimate note is a real cost: a hit needs 13 to 19 digits that pass Luhn
and start with a card-network prefix. Digits may be grouped by spaces, dashes, dots, slashes, underscores or
runs of whitespace (line breaks included). A run longer than 19 digits is searched for a card at its start or
end, or, when it is grouped, as consecutive whole groups. The log formatter does not use this: it masks every
long digit run, Luhn or not (recall over precision, `app.core.logging`)."""

import re
from itertools import islice

# One greedy class after the first digit and no nested quantifier: a run never backtracks, so a scan is linear.
_RUN = re.compile(r"\d[\d\s./_-]*")
SEPARATORS = re.compile(r"[\s./_-]+")
# Work is about 19 steps per digit group. Free-text fields are capped far below this by their schemas (10,000
# characters at most); a longer value is checked on its first 64 KiB.
MAX_SCAN = 65_536
# 4 Visa; 51-55, 2221-2720 Mastercard; 34, 37 Amex; 6011, 644-649, 65 Discover; 3528-3589 JCB; 62 UnionPay.
_PREFIX = tuple(
    ["4", "34", "37", "6011", "65", "62"]
    + [str(n) for n in (*range(51, 56), *range(644, 650), *range(2221, 2721), *range(3528, 3590))]
)


def _luhn(digits: str) -> bool:
    total = 0
    for i, char in enumerate(reversed(digits)):
        n = int(char)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _is_card(digits: str) -> bool:
    return 13 <= len(digits) <= 19 and digits.startswith(_PREFIX) and _luhn(digits)


def _run_has_card(run: str) -> bool:
    groups = [g for g in SEPARATORS.split(run) if g]
    digits = "".join(groups)
    if len(digits) <= 19:
        return _is_card(digits)
    if len(groups) == 1:  # one long contiguous run: a card typed against its start or end
        return any(_is_card(digits[:n]) or _is_card(digits[-n:]) for n in range(13, 20))
    for start in range(len(groups)):  # grouped: consecutive whole groups, as a person types a card among others
        if groups[start][0] not in "23456":
            continue
        window = ""
        for group in islice(groups, start, None):
            window += group
            if len(window) > 19:
                break
            if _is_card(window):
                return True
    return False


def contains_card_number(value: str) -> bool:
    return any(_run_has_card(match.group()) for match in _RUN.finditer(value[:MAX_SCAN]))
