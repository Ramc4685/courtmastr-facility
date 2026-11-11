"""The daily journal entry for accounting export (ADR 0012 section 4): net ledger groups into balanced lines."""

from collections import defaultdict
from dataclasses import dataclass


class UnbalancedJournal(Exception):
    """Sub-ledger transactions balance, so an unbalanced day is a bug: the export aborts."""


@dataclass(frozen=True)
class Line:
    posting_key: str  # e.g. "receivable", "revenue:<category id>", "tax_payable:<tax id>"
    debit_minor: int
    credit_minor: int


def posting_key(account: str, revenue_category_id: object = None, tax_id: object = None) -> str:
    if account == "revenue":
        return f"revenue:{revenue_category_id}"
    if account == "tax_payable":
        return f"tax_payable:{tax_id}"
    return account


def build(rows: list[tuple[str, int, int]]) -> list[Line]:
    """rows: (posting key, debit, credit) for one location-day. One netted line per key, zero lines dropped,
    sorted for a stable document. Raises UnbalancedJournal when debits and credits differ."""
    net: dict[str, int] = defaultdict(int)
    for key, debit, credit in rows:
        net[key] += debit - credit
    lines = [Line(key, max(amount, 0), max(-amount, 0)) for key, amount in sorted(net.items()) if amount]
    debits, credits = sum(line.debit_minor for line in lines), sum(line.credit_minor for line in lines)
    if debits != credits:
        raise UnbalancedJournal(f"debits {debits} != credits {credits}")
    return lines
