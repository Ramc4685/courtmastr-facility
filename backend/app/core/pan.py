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
import unicodedata

# Digit groups joined by separator runs. A separator holds no digit, so each step is unambiguous: linear.
_RUN = re.compile(r"\d+(?:[\s./_,\u2010-\u2015-]+\d+)*")  # dashes of every width and commas too
_GROUP = re.compile(r"\d+")
# Above every scanned field's max_length (the longest, a document template's body_html, is 200,000), so the whole
# accepted value is read; tests/test_pan_detector.py holds every *_html request field to it.
MAX_SCAN = 262_144
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
# prefix -> card lengths, looked up by the first 1 to 4 digits instead of walking 560 prefixes per window
_BY_PREFIX: dict[str, set[int]] = {}
for _prefixes, _lengths in _NETWORKS:
    for _prefix in _prefixes:
        _BY_PREFIX.setdefault(_prefix, set()).update(_lengths)


def _luhn(digits: str) -> bool:
    total = 0
    for i, char in enumerate(reversed(digits)):
        n = int(char)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _is_card(digits: str) -> bool:
    return any(len(digits) in _BY_PREFIX.get(digits[:n], ()) for n in (1, 2, 3, 4)) and _luhn(digits)


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
    # NFKC folds full-width and other compatibility digits to ASCII, so the prefixes match
    value = unicodedata.normalize("NFKC", value[:MAX_SCAN])
    return any(_run_has_card(match.group()) for match in _RUN.finditer(value))
