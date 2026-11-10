"""Process wiring shared by the API, the worker, the relay and scripts: adapters by configuration,
module registration (permission catalogue, authenticator, event subscribers)."""

from app.adapters.email import MemoryEmail, SmtpEmail
from app.core.auth import deps
from app.core.settings import get_settings
from app.ports import email

_done = False


def bootstrap() -> None:
    global _done
    if _done:
        return
    settings = get_settings()
    email.configure(MemoryEmail() if settings.email.adapter == "memory" else SmtpEmail(settings.email))

    from app.modules import platform  # registers the platform permission catalogue and models

    deps.set_authenticator(platform.auth.authenticate)
    _done = True
