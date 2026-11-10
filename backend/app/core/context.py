"""Per-request values that audit rows and log lines need without threading them through every call."""

from contextvars import ContextVar

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)
