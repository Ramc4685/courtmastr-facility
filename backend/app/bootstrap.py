"""Process wiring shared by the API, the worker, the relay and scripts: adapters by configuration,
module registration (permission catalogue, authenticator, event subscribers)."""

from app.adapters.email import MemoryEmail, SmtpEmail
from app.adapters.fake_payments import FakeProvider
from app.adapters.local_storage import LocalStorage
from app.adapters.notifications import EmailNotifier, NoopNotifier
from app.core.auth import deps
from app.core.settings import REPO_ROOT, get_settings
from app.ports import email, notifications, payment_provider, storage

_done = False


def bootstrap() -> None:
    global _done
    if _done:
        return
    settings = get_settings()
    email.configure(MemoryEmail() if settings.email.adapter == "memory" else SmtpEmail(settings.email))

    notifications.configure(NoopNotifier() if settings.notifications.adapter == "noop" else EmailNotifier())
    storage.configure(LocalStorage(REPO_ROOT / settings.storage.local_dir))
    if settings.payments.provider == "fake":
        payment_provider.register(FakeProvider())
    if settings.payments.stripe.enabled:
        from app.adapters.stripe_connect import StripeConnectProvider

        payment_provider.register(StripeConnectProvider.from_environment(settings.payments.stripe))

    # Importing a context registers its permission catalogue, models and event subscribers.
    from app.modules import (  # noqa: F401
        billing,
        clients,
        documents,
        engagement,  # noqa: F401
        memberships,
        packages,
        platform,
        pos,  # noqa: F401
    )

    deps.set_authenticator(platform.auth.authenticate)
    from app.modules import access, programs, rentals, resources, scheduling  # noqa: F401  (modules 2, 3, 10: same registration)

    _done = True
