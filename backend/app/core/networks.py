"""CIDR lists: the one parser and matcher behind the staff IP allow-list, POS registers and the time clock."""

import ipaddress
from collections.abc import Iterable

from app.core.errors import ValidationFailed


def normalize(networks: Iterable[str], pointer: str) -> list[str]:
    """Addresses or CIDR ranges in canonical form ("10.0.0.7/24" -> "10.0.0.0/24"); a bad entry is a 422."""
    out = []
    for index, network in enumerate(networks):
        try:
            out.append(str(ipaddress.ip_network(str(network).strip(), strict=False)))
        except ValueError:
            raise ValidationFailed("Give networks as addresses or CIDR ranges.", pointer=f"{pointer}/{index}") from None
    return out


def contains(networks: Iterable, raw_ip: str | None) -> bool:
    """True when the address lies in any listed network. Not an address (None, a socket path) is never inside."""
    try:
        address = ipaddress.ip_address(raw_ip or "")
    except ValueError:
        return False
    return any(address in ipaddress.ip_network(str(net), strict=False) for net in networks)
