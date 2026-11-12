"""leagues context (L3): sports, competitions (leagues and tournaments), divisions, teams and rosters, team fees
billed through billing, the schedule generator booking courts through scheduling, games, results, standings,
brackets, officials and the public schedule and standings (build module 11). One data model: a league is a
competition, not a separate product.

Public interface: `service`.
"""

from app.modules.leagues import handlers, models, permissions, service

__all__ = ["handlers", "models", "permissions", "service"]
from app.modules.leagues import jobs, subject  # noqa: E402, F401  (registers the job and the merge handlers)
