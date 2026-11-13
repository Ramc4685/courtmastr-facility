"""Events the packages context emits (overview section 2). Ids and the transition, no PII."""

from typing import ClassVar, Literal
from uuid import UUID

from app.core.events import Event


class _PackageEvent(Event):
    aggregate_type: ClassVar[str] = "client_package"
    client_package_id: UUID
    client_id: UUID


class PackageSold(_PackageEvent):
    type: Literal["packages.package.sold"] = "packages.package.sold"


class PackageExhausted(_PackageEvent):
    type: Literal["packages.package.exhausted"] = "packages.package.exhausted"


class PackageExpired(_PackageEvent):
    type: Literal["packages.package.expired"] = "packages.package.expired"


class PackageRenewed(_PackageEvent):
    type: Literal["packages.package.renewed"] = "packages.package.renewed"
    successor_package_id: UUID


class _CreditEvent(_PackageEvent):
    source_type: str | None
    source_id: UUID | None


class CreditConsumed(_CreditEvent):
    type: Literal["packages.credit.consumed"] = "packages.credit.consumed"


class CreditRestored(_CreditEvent):
    type: Literal["packages.credit.restored"] = "packages.credit.restored"


class CreditReservationFailed(Event):
    """A booking named a package that could not pay for it (exhausted, expired, wrong type, not shared). The
    booking context decides what to do; nothing was reserved."""

    aggregate_type: ClassVar[str] = "client_package"
    type: Literal["packages.credit.reservation_failed"] = "packages.credit.reservation_failed"
    client_package_id: UUID
    client_id: UUID
    source_type: str
    source_id: UUID
    code: str


class PostBilledPeriodClosed(Event):
    """A post-billed period close billed its packages (BIL-18)."""

    aggregate_type: ClassVar[str] = "post_billed_close"
    type: Literal["packages.post_billed.period_closed"] = "packages.post_billed.period_closed"
    post_billed_close_id: UUID
    location_id: UUID
    package_count: int
