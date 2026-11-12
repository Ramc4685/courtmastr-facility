"""Outbound HTTP for webhooks: resolve, check every address, then connect to the checked address only.

The check runs at save time and again at every send, and the connection is pinned to the address that passed,
so a DNS answer that changes between the check and the connect (rebinding) cannot reach an internal host.
TLS still verifies the certificate against the URL's host name. Redirects are never followed.
"""

import socket
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpcore

from app.core.errors import ValidationFailed
from app.core.networks import blocked_reason
from app.core.settings import get_settings


class UrlNotAllowed(ValidationFailed):
    code = "url-not-allowed"


@dataclass(frozen=True)
class Target:
    url: str
    host: str
    address: str


def resolve(host: str, port: int) -> list[str]:
    return sorted({info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})


def check(url: str) -> Target:
    """The SSRF guard. Raises UrlNotAllowed (422 url-not-allowed) with the reason."""
    allow_local = get_settings().integrations.webhook_allow_localhost
    parts = urlsplit(url)
    if parts.scheme != "https" and not (allow_local and parts.scheme == "http"):
        raise UrlNotAllowed("The URL must use https", pointer="/url")
    if not parts.hostname or parts.username or parts.password:
        raise UrlNotAllowed("The URL needs a host and must not carry credentials", pointer="/url")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
        addresses = resolve(parts.hostname, port)
    except (OSError, ValueError, UnicodeError):
        raise UrlNotAllowed("The host does not resolve", pointer="/url") from None
    for address in addresses or ["0.0.0.0"]:
        if reason := blocked_reason(address, allow_loopback=allow_local):
            raise UrlNotAllowed(f"The host resolves to a {reason} address", pointer="/url", reason=reason)
    return Target(url, parts.hostname, addresses[0])


class _PinnedBackend(httpcore.SyncBackend):
    def __init__(self, address: str) -> None:
        self.address = address

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        return super().connect_tcp(self.address, port, timeout, local_address, socket_options)


@dataclass(frozen=True)
class Response:
    status: int
    duration_ms: int
    snippet: str  # first 200 bytes of the body, for the error column; never the whole response


def send(target: Target, headers: dict[str, str], body: bytes, timeout: float = 10.0) -> Response:
    started = time.monotonic()
    limits = {"connect": timeout / 2, "read": timeout, "write": timeout, "pool": timeout}
    with (
        httpcore.ConnectionPool(network_backend=_PinnedBackend(target.address)) as pool,
        pool.stream(
            "POST", target.url, headers=list(headers.items()), content=body, extensions={"timeout": limits}
        ) as r,
    ):
        snippet = next(r.iter_stream(), b"")[:200].decode(errors="replace")
        return Response(r.status, int((time.monotonic() - started) * 1000), snippet)
