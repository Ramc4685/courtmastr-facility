"""Process wiring shared by the API, the worker, the relay and scripts: adapters by configuration,
module registration (permission catalogue, authenticator, event subscribers)."""

from app.adapters.email import MemoryEmail, SmtpEmail
from app.adapters.fake_payments import FakeProvider
from app.adapters.local_storage import LocalStorage
from app.adapters.notifications import EmailNotifier, NoopNotifier
from app.adapters.scanner import ClamdScanner, NoopScanner
from app.core.auth import deps
from app.core.settings import REPO_ROOT, get_settings
from app.ports import email, notifications, payment_provider, scanner, storage

_done = False


def bootstrap() -> None:
    global _done
    if _done:
        return
    settings = get_settings()
    email.configure(MemoryEmail() if settings.email.adapter == "memory" else SmtpEmail(settings.email))

    notifications.configure(NoopNotifier() if settings.notifications.adapter == "noop" else EmailNotifier())
    storage.configure(LocalStorage(REPO_ROOT / settings.storage.local_dir))
    if settings.storage.adapter == "s3":
        from app.adapters.s3_storage import S3Storage

        storage.configure(S3Storage(**settings.storage.s3.model_dump()))
    cfg = settings.storage
    scanner.configure(ClamdScanner(cfg.clamd_host, cfg.clamd_port) if cfg.scanner == "clamd" else NoopScanner())
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
        engagement,
        integrations,
        memberships,
        packages,
        platform,
        pos,  # noqa: F401
    )

    deps.set_authenticator(platform.auth.authenticate)
    deps.set_authenticator(integrations.auth.authenticate, prefix="fhk")
    if settings.notifications.adapter != "noop":
        engagement.service.install_notifier()  # transactional notices go through the delivery log and suppressions
    from app.modules import (  # noqa: F401  (build modules 2, 3, 10, 11: same registration)
        access,
        assessments,
        leagues,
        programs,
        rentals,
        reporting,  # noqa: F401  (build module 15)
        resources,
        scheduling,
        staff,  # noqa: F401  (build module 12)
    )

    _done = True
