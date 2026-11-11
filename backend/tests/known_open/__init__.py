"""Cases the generated guards (test_location_scope.py, test_portal_schemas.py) still fail, by the wave 1
hardening finding that will fix them (docs/security/wave1-hardening-spec.md). Each batch owns its own file and
deletes an entry in the commit that fixes it: the cases run as xfail(strict=True), so a fixed case left listed
fails, and a new failure that is not listed fails too. No other xfail belongs in those tests."""

import pytest

from tests.known_open import money, people, space

LOCATION_SCOPE = money.LOCATION_SCOPE | people.LOCATION_SCOPE | space.LOCATION_SCOPE
PORTAL_SCHEMAS = money.PORTAL_SCHEMAS | people.PORTAL_SCHEMAS | space.PORTAL_SCHEMAS


def param(case: str, *values, known: dict[str, str]):
    """A pytest param with id `case`, marked strict xfail when `case` is listed in `known`."""
    marks = [pytest.mark.xfail(strict=True, reason=f"open: {known[case]}")] if case in known else []
    return pytest.param(*values, id=case, marks=marks)
