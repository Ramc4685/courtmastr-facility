"""Portal response schemas, generated from the router table (wave 1 hardening 0.6). A portal route (path under
/portal/ or /public/) never answers with a model a staff route also uses, unless reviewed below, and no
model it returns carries a staff-only field name."""

import re
from typing import get_args

import pytest
from pydantic import BaseModel

from tests.known_open import PORTAL_SCHEMAS, param
from tests.test_location_scope import _keys
from tests.test_security import API, ROUTES

# Models a client may see that staff routes use too, each reviewed.
PORTAL_SAFE_SHARED = {
    "PageInfo": "pagination cursor only",
    "FacilityHoursDay": "public opening hours",
    "InvoiceDocument": "the printed invoice the client receives anyway",
    "DocumentLine": "a line of that printed invoice",
    "DocumentInstalment": "an instalment of that printed invoice",
    "BillingSummary": "the client's own balances",
    "PaymentMethodOut": "brand, last4 and expiry of the client's own stored method",
    "SetupIntentOut": "the processor's client secret for the client's own setup",
    "EmergencyContactOut": "contacts the client entered",
    "EmergencyContactsOut": "list of those contacts",
    "RelationshipTypeOut": "catalogue labels",
    "RelationshipOut": "the client's own links, no staff fields",
    "PreferenceOut": "the client's own communication choices",
    "Preferences": "list of those choices",
    "StandingOut": "a membership standing summary the client sees on the card",
    "ContractQuoteOut": "the price quote the client is buying from",
    "QuotePeriodOut": "a period of that quote",
    "DocumentRequirementOut": "which documents the client still has to sign",
    "DocumentRequirementList": "list of those requirements",
    "Quote": "the price quote the client is buying from",
    "QuoteLine": "a line of that quote",
}
STAFF_ONLY_FIELD = re.compile(r"(_staff_user_id$|^internal_|^actor_|^memo$|^note$|^void_reason$)")


def _models(annotation, seen: set) -> set:
    """Every pydantic model reachable from a type annotation, nested ones included."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation not in seen:
            seen.add(annotation)
            for field in annotation.model_fields.values():
                _models(field.annotation, seen)
    else:
        for arg in get_args(annotation):
            _models(arg, seen)
    return seen


def _is_portal(path: str) -> bool:
    return path.removeprefix(API).startswith(("/portal/", "/public/"))


_PORTAL = [
    (f"{method} {path.removeprefix(API)}", route)
    for path, route, _ in ROUTES
    if _is_portal(path)
    for method in sorted(route.methods)
]
_STAFF_MODELS = set().union(
    *(_models(route.response_model, set()) for _, route, calls in ROUTES if _keys(calls) is not None)
)


@pytest.mark.parametrize(("case", "route"), [param(c, c, r, known=PORTAL_SCHEMAS) for c, r in _PORTAL])
def test_portal_routes_return_portal_schemas(case, route):
    models = _models(route.response_model, set())
    shared = {m.__name__ for m in models & _STAFF_MODELS} - set(PORTAL_SAFE_SHARED)
    assert not shared, f"{case} returns staff models: {sorted(shared)}"
    leaks = {f"{m.__name__}.{f}" for m in models for f in m.model_fields if STAFF_ONLY_FIELD.search(f)}
    assert not leaks, f"{case} returns staff-only fields: {sorted(leaks)}"


def test_the_portal_walk_sees_the_portal():
    assert len(_PORTAL) > 30
    assert set(PORTAL_SCHEMAS) <= {case for case, _ in _PORTAL}, "a known-open entry names no portal route"
