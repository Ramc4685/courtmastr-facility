"""programs context (L3). Thin slice shipped with build module 2: enrolment into a single session, attendance
marks and the session waitlist (CLS-01, CLS-03, CLS-06), so capacity sessions are usable end to end. Build
module 6 completes the context (groups, fees, packages, portal); no table here is renamed.

Public interface: `service`.
"""

from app.modules.programs import handlers, models, service

__all__ = ["handlers", "models", "service"]
