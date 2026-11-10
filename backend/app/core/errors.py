"""Domain errors, rendered as RFC 9457 problem documents by app.core.api (overview 3.13)."""

from typing import Any


class DomainError(Exception):
    status = 400
    code = "bad-request"

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        status: int | None = None,
        persist: bool = False,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(detail or code or self.code)
        self.detail = detail
        self.code = code or self.code
        self.status = status or self.status
        # persist=True commits the request transaction despite the error (failed sign-in counters, audit).
        self.persist = persist
        self.headers = headers or {}
        self.extra = extra


class Unauthenticated(DomainError):
    status, code = 401, "unauthenticated"


class PermissionDenied(DomainError):
    status, code = 403, "permission-denied"


class NotFound(DomainError):
    status, code = 404, "not-found"


class Conflict(DomainError):
    status, code = 409, "invalid-state-transition"


class ValidationFailed(DomainError):
    status, code = 422, "validation-failed"

    def __init__(self, detail: str | None = None, *, pointer: str | None = None, **kwargs: Any) -> None:
        if pointer:
            kwargs["errors"] = [{"pointer": pointer, "code": kwargs.get("code", self.code), "detail": detail}]
        super().__init__(detail, **kwargs)
