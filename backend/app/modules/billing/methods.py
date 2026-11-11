"""The payment processor connection (PAY-11) and stored payment methods (PAY-06, PAY-10).

We keep provider references and display data only: brand, last four, expiry, funding. No card or bank number
reaches this code (ADR 0003 section 5). Functions that take a principal are staff commands; the rest are
internal (the portal and the webhook handler call them after their own checks).
"""

from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.auth import Principal, authorize
from app.core.errors import Conflict, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.core.settings import get_settings
from app.modules import clients, platform
from app.modules.billing import service
from app.modules.billing.models import PaymentMethod, ProviderAccount, ProviderCustomer
from app.ports import payment_provider
from app.ports.payment_provider import AccountState, MethodState

# Called as hook(session, client_id) when a client gets a new autopay method: autopay retries what waited.
AUTOPAY_METHOD_HOOKS: list[Callable[[Session, UUID], None]] = []

# --- provider accounts -------------------------------------------------------------------------------------


def list_provider_accounts(session: Session, principal: Principal) -> list[ProviderAccount]:
    return list(session.scalars(select(ProviderAccount).order_by(ProviderAccount.created_at.desc())))


def _apply_account(account: ProviderAccount, state: AccountState) -> None:
    account.has_card, account.has_bank_debit = state.has_card, state.has_bank_debit
    account.is_payouts_enabled, account.requirements_due = state.is_payouts_enabled, list(state.requirements_due)
    if account.status != "disabled":
        account.status = state.status
        if state.status == "active" and account.connected_at is None:
            account.connected_at = clock.now()


def connect_provider_account(session: Session, principal: Principal, provider_name: str) -> ProviderAccount:
    """Create the tenant's connected account at the processor. One live account per tenant in v1. The account
    starts `pending` and becomes `active` once the owner has finished the processor's own onboarding."""
    authorize(principal, "billing.provider.manage")
    if not payment_provider.registered(provider_name):
        raise Conflict("This payment processor is not enabled on this installation.", code="provider-unavailable")
    live = session.scalar(select(ProviderAccount.id).where(ProviderAccount.status != "disabled"))
    if live is not None:
        raise Conflict("A payment processor is already connected.", code="processor-already-connected")
    tenant = platform.service.get_tenant(session)
    state = payment_provider.get(provider_name).create_account(
        tenant_ref=str(tenant.id), email=principal.email, country=get_settings().payments.default_country,
        currency=tenant.currency,
    )  # fmt: skip
    account = ProviderAccount(provider=provider_name, provider_account_ref=state.provider_account_ref)
    _apply_account(account, state)
    session.add(account)
    session.flush()
    service.register_account_lookup(session, account)
    audit.record(session, "billing.provider.manage", account, changes={"provider": [None, provider_name]})
    return account


def refresh_provider_account(session: Session, account_id: UUID) -> ProviderAccount:
    """Mirror the processor's capability state (after onboarding, or when it tells us the account changed)."""
    account = service._lock(session, ProviderAccount, account_id)
    was = account.status
    state = payment_provider.get(account.provider).get_account(account_ref=account.provider_account_ref)
    _apply_account(account, state)
    if account.status != was:
        audit.record(session, "billing.provider.manage", account, changes={"status": [was, account.status]})
    session.flush()
    return account


def create_onboarding_link(session: Session, principal: Principal, account_id: UUID) -> str:
    """A single-use link to the processor's hosted onboarding. The return address is ours and fixed, never
    taken from the request."""
    authorize(principal, "billing.provider.manage")
    account = service._get(session, ProviderAccount, account_id)
    if account.status == "disabled":
        raise Conflict("This processor account is disconnected.", code="processor-not-connected")
    back = f"{get_settings().app.web_base_url}/billing/setup"
    return payment_provider.get(account.provider).onboarding_link(
        account_ref=account.provider_account_ref, return_url=back, refresh_url=back
    )


def disconnect_provider_account(session: Session, principal: Principal, account_id: UUID) -> ProviderAccount:
    """Stop using a processor account. The row stays for history; stored methods on it stop being usable."""
    authorize(principal, "billing.provider.manage")
    account = service._lock(session, ProviderAccount, account_id)
    if account.status == "disabled":
        raise Conflict("This processor account is already disconnected.", code="processor-not-connected")
    was, account.status, account.disabled_at = account.status, "disabled", clock.now()
    for method in session.scalars(
        select(PaymentMethod).where(PaymentMethod.provider_account_id == account.id, PaymentMethod.status != "removed")
    ):
        method.status, method.removed_at, method.is_autopay = "removed", clock.now(), False
    audit.record(session, "billing.provider.manage", account, changes={"status": [was, "disabled"]})
    session.flush()
    return account


# --- stored methods ----------------------------------------------------------------------------------------


def _customer_ref(session: Session, account: ProviderAccount, client_id: UUID) -> str:
    stmt = select(ProviderCustomer).where(
        ProviderCustomer.client_id == client_id, ProviderCustomer.provider_account_id == account.id
    )
    customer = session.execute(stmt).scalar_one_or_none()
    if customer is None:
        ref = payment_provider.get(account.provider).ensure_customer(
            account_ref=account.provider_account_ref, client_ref=str(client_id),
            idempotency_key=f"{session.info['tenant_id']}:customer:{client_id}",
        )  # fmt: skip
        customer = ProviderCustomer(client_id=client_id, provider_account_id=account.id, provider_customer_ref=ref)
        session.add(customer)
        session.flush()
    return customer.provider_customer_ref


def _apply_method(method: PaymentMethod, state: MethodState) -> None:
    method.kind, method.brand, method.last4 = state.kind, state.brand, state.last4
    method.exp_month, method.exp_year = state.exp_month, state.exp_year
    method.funding, method.wallet, method.mandate_ref = state.funding, state.wallet, state.mandate_ref


def _autopay_method(session: Session, client_id: UUID) -> PaymentMethod | None:
    return session.execute(
        select(PaymentMethod).where(
            PaymentMethod.client_id == client_id, PaymentMethod.is_autopay, PaymentMethod.status == "active"
        )
    ).scalar_one_or_none()


def autopay_method(session: Session, client_id: UUID) -> PaymentMethod | None:
    """The one stored method autopay may charge for this payer, if any."""
    return _autopay_method(session, client_id)


def _make_autopay(session: Session, method: PaymentMethod) -> None:
    """One autopay method per client: the previous one is cleared in the same transaction."""
    current = _autopay_method(session, method.client_id)
    if current is not None and current.id != method.id:
        current.is_autopay = False
        session.flush()
    method.is_autopay = True
    session.flush()
    for hook in AUTOPAY_METHOD_HOOKS:
        hook(session, method.client_id)


def create_setup(session: Session, client_id: UUID, kinds: tuple[str, ...] = ("card",)) -> dict:
    """Start saving a method: returns the secret the processor's hosted fields need. Nothing is stored yet."""
    clients.service.require_active(session, client_id)
    account = service._provider_account(session)
    setup = payment_provider.get(account.provider).create_setup(
        account_ref=account.provider_account_ref, customer_ref=_customer_ref(session, account, client_id), kinds=kinds
    )
    return {
        "provider": account.provider, "client_secret": setup.client_secret,
        **payment_provider.browser_keys(account.provider, account.provider_account_ref),
    }  # fmt: skip


def attach_method(session: Session, client_id: UUID, method_token: str, *, is_autopay: bool | None = None):
    """Store a tokenised card or bank account for a client. A bank account that still needs micro-deposit
    verification is stored `pending_verification` and cannot be charged. The client's first usable method
    becomes their autopay method unless told otherwise."""
    clients.service.require_active(session, client_id)
    account = service._provider_account(session)
    provider = payment_provider.get(account.provider)
    try:
        state = provider.attach_method(
            account_ref=account.provider_account_ref, customer_ref=_customer_ref(session, account, client_id),
            method_token=method_token,
        )  # fmt: skip
    except ValueError as error:
        raise ValidationFailed(str(error), pointer="/method_token", code="payment-method-rejected") from None
    method = session.execute(
        select(PaymentMethod).where(
            PaymentMethod.provider_account_id == account.id,
            PaymentMethod.provider_method_ref == state.provider_method_ref,
        )
    ).scalar_one_or_none()
    if method is None:
        method = PaymentMethod(
            client_id=client_id, provider_account_id=account.id, provider_method_ref=state.provider_method_ref,
            is_autopay=False, status="active" if state.usable else "pending_verification",
            verified_at=clock.now() if state.usable and state.kind == "bank_account" else None,
        )  # fmt: skip
        _apply_method(method, state)
        session.add(method)
        session.flush()
        audit.record(
            session, "billing.payment_method.manage", method, changes={"kind": [None, method.kind], "added": True}
        )
    wants = _autopay_method(session, client_id) is None if is_autopay is None else is_autopay
    if wants and method.status == "active" and not method.is_autopay:
        _make_autopay(session, method)
    return method


def _live(session: Session, method_id: UUID) -> PaymentMethod:
    method = service._lock(session, PaymentMethod, method_id)
    if method.status == "removed":
        raise Conflict("This payment method was removed.", code="payment-method-removed")
    return method


def set_autopay(session: Session, method_id: UUID, is_autopay: bool) -> PaymentMethod:
    method = _live(session, method_id)
    if is_autopay and method.status != "active":
        raise Conflict("Only a usable payment method can be used for autopay.", code="payment-method-not-usable")
    if is_autopay and not method.is_autopay:
        _make_autopay(session, method)
    elif not is_autopay:
        method.is_autopay = False
    audit.record(session, "billing.payment_method.manage", method, changes={"is_autopay": [not is_autopay, is_autopay]})
    session.flush()
    return method


def verify_bank_account(session: Session, method_id: UUID, amounts: tuple[int, ...]) -> PaymentMethod:
    """Confirm the two micro-deposits. A wrong answer changes nothing and may be tried again."""
    method = _live(session, method_id)
    if method.status != "pending_verification":
        raise Conflict("This payment method does not need verifying.", code="payment-method-not-pending")
    account = session.get(ProviderAccount, method.provider_account_id)
    state = payment_provider.get(account.provider).verify_method(
        account_ref=account.provider_account_ref, provider_method_ref=method.provider_method_ref, amounts=amounts
    )
    if not state.usable:
        raise ValidationFailed("Those amounts do not match.", pointer="/amounts", code="verification-failed")
    method.status, method.verified_at = "active", clock.now()
    audit.record(
        session, "billing.payment_method.manage", method, changes={"status": ["pending_verification", "active"]}
    )
    session.flush()
    if _autopay_method(session, method.client_id) is None:
        _make_autopay(session, method)
    return method


def remove_method(session: Session, method_id: UUID) -> PaymentMethod:
    method = _live(session, method_id)
    account = session.get(ProviderAccount, method.provider_account_id)
    payment_provider.get(account.provider).detach_method(
        account_ref=account.provider_account_ref, provider_method_ref=method.provider_method_ref
    )
    was, method.status, method.removed_at, method.is_autopay = method.status, "removed", clock.now(), False
    audit.record(session, "billing.payment_method.manage", method, changes={"status": [was, "removed"]})
    session.flush()
    return method


def suspend_method(session: Session, method_id: UUID) -> None:
    """The bank or network says the method is gone (closed account, revoked mandate): never charge it again."""
    method = service._lock(session, PaymentMethod, method_id)
    if method.status == "active":
        method.status, method.suspended_on, method.is_autopay = "suspended", clock.now().date(), False
        audit.record(session, "billing.payment_method.manage", method, changes={"status": ["active", "suspended"]})
        session.flush()


def sync_method(session: Session, provider_method_ref: str) -> None:
    """The processor says a stored method changed (the card networks' updater replaced an expired card)."""
    method = session.execute(
        select(PaymentMethod).where(PaymentMethod.provider_method_ref == provider_method_ref)
    ).scalar_one_or_none()
    if method is None or method.status == "removed":
        return
    account = session.get(ProviderAccount, method.provider_account_id)
    _apply_method(
        method,
        payment_provider.get(account.provider).get_method(
            account_ref=account.provider_account_ref, provider_method_ref=provider_method_ref
        ),
    )
    session.flush()


def methods_of(session: Session, client_id: UUID) -> list[PaymentMethod]:
    return list(
        session.scalars(
            select(PaymentMethod)
            .where(PaymentMethod.client_id == client_id, PaymentMethod.status != "removed")
            .order_by(PaymentMethod.created_at)
        )
    )


# --- staff commands (client-following keys: holding the key at any location suffices) ---------------------


def list_client_methods(session: Session, principal: Principal, client_id: UUID) -> list[PaymentMethod]:
    authorize(principal, "billing.payment_method.read")
    clients.service.get(session, client_id)
    return methods_of(session, client_id)


def list_methods(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Every stored method (PAY-07 expiring cards: filter exp_year and exp_month, sort by expiry)."""
    authorize(principal, "billing.payment_method.read")
    return paginate(
        session, select(PaymentMethod).where(PaymentMethod.status != "removed"), query, id_column=PaymentMethod.id,
        sort_fields={"exp_year": PaymentMethod.exp_year, "created_at": PaymentMethod.created_at},
        default_sort="exp_year",
        filter_fields={
            "client_id": PaymentMethod.client_id, "kind": PaymentMethod.kind, "status": PaymentMethod.status,
            "is_autopay": PaymentMethod.is_autopay, "exp_year": PaymentMethod.exp_year,
            "exp_month": PaymentMethod.exp_month,
        },
    )  # fmt: skip


def create_client_setup(session: Session, principal: Principal, client_id: UUID, kinds: tuple[str, ...]) -> dict:
    authorize(principal, "billing.payment_method.manage")
    clients.service.get(session, client_id)
    return create_setup(session, client_id, kinds)


def attach_client_method(session: Session, principal: Principal, client_id: UUID, data: dict) -> PaymentMethod:
    authorize(principal, "billing.payment_method.manage")
    clients.service.get(session, client_id)
    return attach_method(session, client_id, data["method_token"], is_autopay=data.get("is_autopay"))


def update_method(session: Session, principal: Principal, method_id: UUID, data: dict) -> PaymentMethod:
    authorize(principal, "billing.payment_method.manage")
    service._get(session, PaymentMethod, method_id)
    return set_autopay(session, method_id, data["is_autopay"])


def remove_client_method(session: Session, principal: Principal, method_id: UUID) -> None:
    authorize(principal, "billing.payment_method.manage")
    service._get(session, PaymentMethod, method_id)
    remove_method(session, method_id)


def verify_client_bank_account(session: Session, principal: Principal, method_id: UUID, amounts: list[int]):
    authorize(principal, "billing.payment_method.manage")
    service._get(session, PaymentMethod, method_id)
    return verify_bank_account(session, method_id, tuple(amounts))
