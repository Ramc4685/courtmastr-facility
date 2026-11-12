"""CIDR lists (the staff IP allow-list, POS registers, the time clock) and the outbound SSRF address policy
(webhooks, OIDC discovery)."""

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


# Ranges a client on the internet never arrives from: a staff allow-list entry here can only match a proxy or
# a neighbour on the API's own network (unspecified, private, shared/CGNAT, loopback, link-local, ULA).
NOT_A_CLIENT = [
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16",
    "::/128", "::1/128", "fc00::/7", "fe80::/10",
]  # fmt: skip


def overlaps(network: str, others: Iterable) -> bool:
    """True when the CIDR shares any address with a listed network (same IP version only)."""
    net = ipaddress.ip_network(str(network), strict=False)
    return any(
        net.version == other.version and net.overlaps(other)
        for other in (ipaddress.ip_network(str(o), strict=False) for o in others)
    )


# IPv6 forms that carry an IPv4 address a gateway may translate to (W2-04). Python 3.12 calls NAT64 and
# IPv4-compatible addresses global, so 64:ff9b::a00:1 would otherwise reach 10.0.0.1.
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_IPV4_COMPATIBLE = ipaddress.ip_network("::/96")


def blocked_reason(address: str, *, allow_loopback: bool = False) -> str | None:
    """Why an outbound target address is refused, or None. Anything not globally routable is refused:
    private, loopback, link-local (cloud metadata 169.254.169.254 included), shared, reserved, multicast,
    and IPv6 forms that embed an IPv4 address (NAT64, IPv4-compatible, 6to4, Teredo)."""
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped  # ::ffff:10.0.0.1 is 10.0.0.1
        elif not (ip.is_loopback or ip.is_unspecified) and (
            ip in _NAT64 or ip in _IPV4_COMPATIBLE or ip.sixtofour or ip.teredo
        ):
            return "embedded-ipv4"
    if ip.is_loopback:
        return None if allow_loopback else "loopback"
    for reason, test in (
        ("unspecified", ip.is_unspecified),
        ("link-local", ip.is_link_local),
        ("multicast", ip.is_multicast),
        ("private", ip.is_private),
    ):
        if test:
            return reason
    return None if ip.is_global else "reserved"
