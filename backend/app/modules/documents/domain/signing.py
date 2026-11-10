"""Who must sign and what the decisions add up to (data-model 2.5, state machine 7.6).

A template version lists its signature blocks, one per signer role. For a minor the guardian's signature binds
and the minor's own is optional; for an adult a guardian block is not asked for. Any decline declines the
document; it is accepted once every required role has accepted.
"""

from collections.abc import Iterable, Mapping

ROLES = ("client", "guardian", "co_signer")
DEFAULT_BLOCKS = [{"role": "client", "label": "Signature"}]


def check_blocks(blocks: list[dict]) -> str | None:
    """An error message, or None when the blocks are usable."""
    roles = [b["role"] for b in blocks]
    if not roles:
        return "At least one signature block is required."
    if len(set(roles)) != len(roles):
        return "Each signer role may appear once."
    if roles == ["guardian"]:
        return "A guardian block needs a client block beside it."
    return None


def required_roles(blocks: Iterable[Mapping], requires_guardian: bool) -> set[str]:
    roles = {b["role"] for b in blocks}
    if requires_guardian:
        return (roles - {"client"}) | {"guardian"}
    return roles - {"guardian"}


def outcome(required: set[str], decisions: Mapping[str, str]) -> str:
    """pending | accepted | declined from {role: decision} recorded so far."""
    if "declined" in decisions.values():
        return "declined"
    if required <= {role for role, decision in decisions.items() if decision == "accepted"}:
        return "accepted"
    return "pending"
