"""The kernel's billing fixtures, shared with the build module 8 test files."""

from app.modules.billing.tests.test_billing import desk, shop  # noqa: F401
from app.modules.billing.tests.test_surface import api, member  # noqa: E402, F401  (statements tests use them)
