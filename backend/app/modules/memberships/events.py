"""Events the memberships context emits (overview section 2, ADR 0005). Ids and the transition, no PII."""

from datetime import date
from typing import ClassVar, Literal
from uuid import UUID

from app.core.events import Event


class _ContractEvent(Event):
    aggregate_type: ClassVar[str] = "membership_contract"
    contract_id: UUID
    client_id: UUID


class ContractActivated(_ContractEvent):
    """The contract became usable: sold active, its start date arrived, its document was accepted, a suspension
    ended or a cancel was undone (`reason`)."""

    type: Literal["memberships.contract.activated"] = "memberships.contract.activated"
    reason: str = "start"


class ContractRenewed(_ContractEvent):
    """Fires when the successor is created, with its price and start, so a renewal notice can go out."""

    type: Literal["memberships.contract.renewed"] = "memberships.contract.renewed"
    successor_contract_id: UUID
    start_on: date
    term_fee_minor: int


class ContractFrozen(_ContractEvent):
    type: Literal["memberships.contract.frozen"] = "memberships.contract.frozen"


class ContractUnfrozen(_ContractEvent):
    type: Literal["memberships.contract.unfrozen"] = "memberships.contract.unfrozen"


class ContractSuspended(_ContractEvent):
    type: Literal["memberships.contract.suspended"] = "memberships.contract.suspended"


class ContractCancelled(_ContractEvent):
    type: Literal["memberships.contract.cancelled"] = "memberships.contract.cancelled"
    reason: str | None = None
    cancel_packages: bool = False  # the cancel dialog's answer for packages bundled with this contract


class ContractExpired(_ContractEvent):
    type: Literal["memberships.contract.expired"] = "memberships.contract.expired"
