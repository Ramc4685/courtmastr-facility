"""Card number (PAN) detector for stored free-text input (`app.core.schemas.In`, security-baseline section 3).

Favours precision, since refusing a legitimate note is a real cost. A hit is a candidate whose network prefix and
length agree (Visa 16 or 19; Mastercard 16; Amex 15; Discover, JCB and UnionPay 16 to 19) and that passes Luhn.
13-digit Visa is not detected: it is retired, and every valid EAN-13 barcode starting with 4 would look like one.

Digit groups are split by any run of separators (whitespace, line breaks, dashes, dots, slashes, underscores). A
candidate is a window of consecutive whole groups, of any sizes, whose joined length is a card length for its
prefix: "4111 1111 1111 1111", "41111111 11111111", "4111-1111--1111 1111" and "4111 1111 11111111" all are.
Every group in a window has at least 3 digits, which keeps lists of scores and similar short numbers out
("51 48 55 60 52 47 63 58"). An unbroken run longer than a card is checked at its start and end.

This is a best-effort guard against accidental entry, not a guarantee. The log formatter does not use it: it masks
every long digit run, Luhn or not, and is the stricter of the two (`app.core.logging`)."""

import re

# Digit groups joined by separator runs. A separator holds no digit, so each step is unambiguous: linear.
_RUN = re.compile(r"\d+(?:[\s./_-]+\d+)*")
_GROUP = re.compile(r"\d+")
# Free-text fields are capped far below this by their schemas (10,000 characters at most); a longer value is
# checked on its first 64 KiB.
MAX_SCAN = 65_536
_MIN_GROUP = 3
_NETWORKS = (  # (prefixes, lengths)
    (("4",), (16, 19)),
    (tuple(str(n) for n in (*range(51, 56), *range(2221, 2721))), (16,)),
    (("34", "37"), (15,)),
    (("6011", "65", *(str(n) for n in range(644, 650))), (16, 17, 18, 19)),
    (tuple(str(n) for n in range(3528, 3590)), (16, 17, 18, 19)),
    (("62",), (16, 17, 18, 19)),
)
_LENGTHS = sorted({n for _, lengths in _NETWORKS for n in lengths})


def _luhn(digits: str) -> bool:
    total = 0
    for i, char in enumerate(reversed(digits)):
        n = int(char)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _is_card(digits: str) -> bool:
    return any(digits.startswith(p) and len(digits) in n for p, n in _NETWORKS) and _luhn(digits)


def _unbroken_has_card(digits: str) -> bool:
    if len(digits) <= 19:
        return _is_card(digits)
    return any(_is_card(digits[:n]) or _is_card(digits[-n:]) for n in _LENGTHS)  # typed against a reference


def _run_has_card(run: str) -> bool:
    groups = _GROUP.findall(run)
    if any(len(g) > _LENGTHS[-1] and _unbroken_has_card(g) for g in groups):
        return True
    for start in range(len(groups)):
        digits = ""
        for end in range(start, len(groups)):  # at most 6 groups fit in 19 digits, so this stays linear
            group = groups[end]
            if len(group) < _MIN_GROUP or len(digits) + len(group) > _LENGTHS[-1]:
                break
            digits += group
            if _is_card(digits):
                return True
    return False


def contains_card_number(value: str) -> bool:
    return any(_run_has_card(match.group()) for match in _RUN.finditer(value[:MAX_SCAN]))
