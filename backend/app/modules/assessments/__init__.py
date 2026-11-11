"""assessments context (build module 13): assessment categories and numeric fields, results recorded per
client, per-field history, and a client-visible progress view on the portal (FIT-01 to FIT-03, FIT-05 view).

Public interface: `service`.
"""

from app.modules.assessments import models, permissions, service

__all__ = ["models", "permissions", "service"]
from app.modules.assessments import subject  # noqa: E402, F401  (registers the merge and data-subject handlers)
