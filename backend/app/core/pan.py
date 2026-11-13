"""Card number (PAN) detector: Luhn-valid digit runs of 13 to 19 digits, optionally grouped by single spaces or
dashes, with a card-network prefix (security-baseline section 3, free-text leakage). Used on free-text input
(`app.core.schemas.In`) and by the log formatter."""

import re

# A whole run only: never starts or ends next to another digit, so a 20-digit reference is not searched for a card.
# Linear on hostile input: the only inner quantifier is `[ -]?`, disjoint from `\d`, so each step has exactly one
# way to match and a start position backtracks at most 18 times (test_detector_is_linear_on_hostile_input).
_RUN = re.compile(r"(?<!\d)(?<!\d[ -])\d(?:[ -]?\d){12,18}(?![ -]?\d)")
MAX_SCAN = 1_048_576  # the API's request body cap (api.max_body_bytes): nothing longer reaches a schema


def _luhn(digits: str) -> bool:
    total = 0
    for i, char in enumerate(reversed(digits)):
        n = int(char)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _is_card(run: str) -> bool:
    digits = re.sub(r"[ -]", "", run)
    # Amex, Diners, JCB (3), Visa (4), Mastercard and Maestro (5, 2221-2720), Discover and UnionPay (6): a run
    # that starts like a date or an order year is not a card, which keeps "2026-11-13 2026-12-01" out.
    network = digits[0] in "3456" or 2221 <= int(digits[:4]) <= 2720
    return network and _luhn(digits)


def contains_card_number(value: str) -> bool:
    return any(_is_card(match.group()) for match in _RUN.finditer(value[:MAX_SCAN]))


def mask_card_numbers(value: str, mask: str = "[card]") -> str:
    return _RUN.sub(lambda m: mask if _is_card(m.group()) else m.group(), value[:MAX_SCAN])
