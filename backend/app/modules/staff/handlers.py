"""Subscribers of the staff context: the independent coaches' earnings ledger follows the money (staff README "Coach
revenue share"). Each runs as a tenant actor, once per event, and `coach.reconcile_*` is idempotent besides."""

from uuid import UUID

from app.core.events import handles
from app.modules.staff import coach


@handles("packages.credit.consumed")
def earn_on_credit_consumed(session, payload: dict) -> None:
    """A lesson credit was spent (attended, or a no-show the package charges): the lesson is recognised. The whole
    package is reconciled, since a lesson's value depends on its place among the package's spent credits."""
    coach.reconcile_package(session, UUID(payload["client_package_id"]))


@handles("packages.credit.restored")
def reverse_on_credit_restored(session, payload: dict) -> None:
    """The credit came back (excused, cancelled in time, session cancelled): the lesson's earning is reversed, and a
    lesson past the sold count may move up into a paid place."""
    coach.reconcile_package(session, UUID(payload["client_package_id"]))


def _package_charge(session, payload: dict) -> None:
    if (payload.get("source_context"), payload.get("source_type")) == ("packages", "client_package"):
        coach.reconcile_package(session, UUID(payload["source_id"]))


@handles("billing.charge.reversed")
def revalue_on_charge_reversed(session, payload: dict) -> None:
    """A refund starts with reversing the package charge: the lessons it paid for are revalued."""
    _package_charge(session, payload)


@handles("billing.charge.voided")
def revalue_on_charge_voided(session, payload: dict) -> None:
    """A voided package charge leaves the package with no revenue: the lessons it paid for are reversed."""
    _package_charge(session, payload)


@handles("billing.charge.adjusted")
def revalue_on_charge_adjusted(session, payload: dict) -> None:
    _package_charge(session, payload)
