"""Card number (PAN) detector for stored free-text input (`app.core.schemas.In`, security-baseline section 3).

Favours precision, since refusing a legitimate note is a real cost. A hit is a candidate whose network prefix and
length agree (Visa 16 or 19; Mastercard 16; Amex 15; Discover, JCB and UnionPay 16 to 19) and that passes Luhn.
13-digit Visa is not detected: it is retired, and every valid EAN-13 barcode starting with 4 would look like one.

A candidate is written the way a card is: unbroken, or grouped 4-4-4-4, 4-4-4-4-3 or 4-6-5, the groups joined by
one separator (a space, dash, dot, slash or underscore, optionally spaced, or any run of whitespace, line breaks
included). Short tokens are never joined into a candidate ("scores 51 48 55 60 52 47 63 58"), but a card grouping
is found among other groups ("ref 1234 4111 1111 1111 1111"), and an unbroken run longer than a card is checked
at its start and end. The log formatter does not use this: it masks every long digit run, Luhn or not (recall
over precision, `app.core.logging`)."""

import re

# Digit groups joined by single separators. A separator holds no digit, so each step is unambiguous: linear.
_RUN = re.compile(r"\d+(?:(?:[ \t]*[./_-][ \t]*|\s+)\d+)*")
_GROUP = re.compile(r"\d+")
# Free-text fields are capped far below this by their schemas (10,000 characters at most); a longer value is
# checked on its first 64 KiB.
MAX_SCAN = 65_536
_GROUPINGS = ((4, 4, 4, 4), (4, 4, 4, 4, 3), (4, 6, 5))
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
    if any(len(g) >= 15 and _unbroken_has_card(g) for g in groups):
        return True
    sizes = [len(g) for g in groups]
    for start in range(len(groups)):
        for grouping in _GROUPINGS:
            end = start + len(grouping)
            if tuple(sizes[start:end]) == grouping and _is_card("".join(groups[start:end])):
                return True
    return False


def contains_card_number(value: str) -> bool:
    return any(_run_has_card(match.group()) for match in _RUN.finditer(value[:MAX_SCAN]))
