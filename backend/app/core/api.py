"""HTTP plumbing shared by every router: the request transaction, problem+json errors, request context."""

import ipaddress
import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import IntegrityError
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core import context, crypto, idempotency, networks
from app.core.db.session import run_after_commit
from app.core.errors import DomainError, PermissionDenied, ValidationFailed
from app.core.ids import new_id
from app.core.pan import contains_card_number
from app.core.schemas import CARD_DATA, CARD_DATA_DETAIL, NOT_FREE_TEXT
from app.core.settings import get_settings

log = logging.getLogger("app.request")
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{8,64}")
# Paths whose next segment is a credential (calendar feed tokens): logged up to the prefix whatever the method,
# trailing slash or deeper path, so no route has to redact for the log.
_SECRET_PATH_PREFIXES = ("/api/v1/public/calendar-feeds/",)


def _loggable_path(path: str) -> str:
    folded = re.sub("/+", "/", path).casefold()  # routing may not match these, but the log line comes first
    for prefix in _SECRET_PATH_PREFIXES:
        if folded.startswith(prefix):
            return prefix + "[redacted]"
    return path


# Constraint name -> problem code, for constraints whose meaning is richer than "already exists".
# Contexts register theirs (ex_resource_hold_overlap -> booking-conflict). Unmapped = 500 = a bug.
CONSTRAINT_CODES: dict[str, str] = {}
# Unique constraint -> the API field to blame, where the name does not already end in it.
CONSTRAINT_FIELDS: dict[str, str] = {"uq_identity_kind_email": "email"}


def camel_id(route) -> str:
    """operationId from the handler name: create_booking -> createBooking (the spec's operationIds)."""
    head, *rest = route.name.split("_")
    return head + "".join(part.title() for part in rest)


def problem(request: Request, status: int, code: str, detail: str | None = None, headers=None, **extra: Any):
    body = {
        "type": f"/problems/{code}",
        "title": code.replace("-", " ").capitalize(),
        "status": status,
        "code": code,
        "instance": request.url.path,
        "trace_id": context.request_id.get(),
    }
    if detail and status < 500:
        body["detail"] = detail
    body.update(extra)
    return JSONResponse(body, status, headers=headers, media_type="application/problem+json")


def _finish(request: Request, exc: BaseException | None, response=None) -> None:
    """Commit or roll back the request transaction opened by the auth dependencies."""
    session = getattr(request.state, "session", None)
    claim = getattr(request.state, "idempotency", None)
    if session is None:
        return
    request.state.session = None
    committed = False
    try:
        if exc is None or getattr(exc, "persist", False):
            if claim and exc is None:
                secret = idempotency.is_secret(request)
                body = json.loads(response.body) if response.body and not secret else None
                idempotency.complete(session, *claim, response.status_code, body)
            session.commit()
            if exc is None:
                response.background = BackgroundTask(run_after_commit, session)
                return
            committed = True
        else:
            session.rollback()
    except BaseException:
        session.rollback()
        if claim:
            idempotency.abandon(session.info["tenant_id"], *claim)
        raise
    finally:
        session.close()
    if committed:  # a persisted error (failed sign-in, lockout) still sends what it queued, e.g. the lockout email
        run_after_commit(session)
    if claim:
        idempotency.abandon(session.info["tenant_id"], *claim)


def _check_origin(request: Request) -> None:
    """Browsers attach cookies on their own, so an unsafe request a browser sends must come from our own
    pages (security-baseline 5.3 item 2). Non-browser clients send neither header and pass; bearer callers
    are exempt because a cross-site page cannot add Authorization without a CORS preflight we never grant.
    This also covers the routes the session-bound CSRF token cannot: sign-in and cookie refresh."""
    if request.method in ("GET", "HEAD", "OPTIONS") or "authorization" in request.headers:
        return
    origin = request.headers.get("origin")
    foreign = origin is not None and (
        urlsplit(origin).netloc != request.headers.get("host") and origin != get_settings().app.web_base_url
    )
    if foreign or request.headers.get("sec-fetch-site") == "cross-site":
        raise PermissionDenied("Cross-site request refused.", code="csrf-failed")


def _refuse_card_data_in_query(request: Request) -> None:
    """A write's query values are stored like body fields (a photo caption), so In's card scan applies to them by
    the same name rules. Path segments are ids and keys, and reads only filter. shortcut: no route takes a form
    (python-multipart is not installed); scan form values here when one is added.

    First, on every method: Postgres text cannot hold NUL (a filter or path value with one is a 500), so a NUL in
    any query name or value or path value is refused, as core.schemas.In does for request bodies."""
    for where, pairs in (("query", request.query_params.multi_items()), ("path", request.path_params.items())):
        for name, value in pairs:
            if "\x00" in name or (isinstance(value, str) and "\x00" in value):
                raise ValidationFailed("Text cannot contain a NUL character.", pointer=f"/{where}")
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    errors = [
        {"type": CARD_DATA, "loc": ("query", name), "msg": CARD_DATA_DETAIL}
        for name, value in request.query_params.multi_items()
        if name not in NOT_FREE_TEXT and contains_card_number(value)
    ]
    if errors:
        raise RequestValidationError(errors)


class TxRoute(APIRoute):
    """One transaction per request, committed before the response is sent (never in a dependency teardown,
    which may run after it). Also where an Idempotency-Key is honoured."""

    def get_route_handler(self):
        inner = super().get_route_handler()

        async def handler(request: Request):
            _check_origin(request)
            _refuse_card_data_in_query(request)
            if "idempotency-key" in request.headers:
                raw = request.method.encode() + request.url.path.encode() + await request.body()
                request.state.body_hash = crypto.mac_bytes(raw)
            try:
                response = await inner(request)
            except idempotency.Replay as replay:
                await run_in_threadpool(_finish, request, replay)
                return JSONResponse(replay.body, replay.status, headers={"Idempotent-Replayed": "true"})
            except BaseException as exc:
                await run_in_threadpool(_finish, request, exc)
                raise
            await run_in_threadpool(_finish, request, None, response)
            return response

        return handler


def _ip(scope) -> str | None:
    """The client address (inet columns reject anything else, e.g. a unix socket path). The socket peer, unless
    the peer is a configured trusted proxy: then the right-most X-Forwarded-For hop that is not itself a trusted
    proxy (baseline 5.1). The left-most hops are client-supplied and never believed."""
    try:
        peer = str(ipaddress.ip_address(scope["client"][0]))
    except (KeyError, TypeError, ValueError):
        return None
    trusted = get_settings().api.trusted_proxies
    if not trusted or not networks.contains(trusted, peer):
        return peer
    forwarded = b",".join(value for name, value in scope["headers"] if name == b"x-forwarded-for").decode("latin-1")
    for hop in reversed([part.strip() for part in forwarded.split(",") if part.strip()]):
        if not networks.contains(trusted, hop):
            try:
                return str(ipaddress.ip_address(hop))
            except ValueError:
                return None  # a malformed hop after our proxy: refuse to guess
    return peer


class RequestContextMiddleware:
    """Trace id in and out, and one structured log line per request (ids only, no PII)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        supplied = headers.get(b"x-request-id", b"").decode("latin-1")
        request_id = supplied if _REQUEST_ID.fullmatch(supplied) else str(new_id())
        context.request_id.set(request_id)
        context.client_ip.set(_ip(scope))
        state = scope.setdefault("state", {})
        started, status = time.perf_counter(), 500

        async def send_with_id(message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            principal = state.get("principal")
            log.info(
                "request",
                extra={
                    "method": scope["method"],
                    "path": _loggable_path(scope["path"]),
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "tenant_id": state.get("tenant_id"),
                    "principal_id": principal.actor_id if principal else None,
                },
            )


_HEADERS = {
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"DENY",
    b"referrer-policy": b"no-referrer",
    b"cross-origin-opener-policy": b"same-origin",
    b"permissions-policy": b"camera=(self), microphone=(), geolocation=(), payment=(self)",
    # The API serves data, never a page that should load anything (the interactive docs page is exempt).
    b"content-security-policy": b"default-src 'none'; frame-ancestors 'none'",
    b"cache-control": b"no-store",
}


class SecurityHeadersMiddleware:
    """Standard response headers (security-baseline 9.6 and V8). A header the handler set itself wins."""

    def __init__(self, app) -> None:
        self.app = app
        self.headers = dict(_HEADERS)
        if get_settings().auth.cookie_secure:  # only meaningful, and only safe, behind TLS
            self.headers[b"strict-transport-security"] = b"max-age=31536000; includeSubDomains"

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        is_docs = scope["path"].endswith("/docs")

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                present = {name.lower() for name, _ in headers}
                for name, value in self.headers.items():
                    if name not in present and not (is_docs and name == b"content-security-policy"):
                        headers.append((name, value))
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodyLimitMiddleware:
    """Refuse request bodies over api.max_body_bytes with 413, by Content-Length or by counting a chunked
    body. One small cap fits everything except the routes in UPLOAD_PATHS, which take file bytes up to
    storage.max_upload_bytes (security-baseline 8)."""

    UPLOAD_PATHS = re.compile(
        r"^/api/v1/client-documents/[^/]+/paper-scan$"
        r"|^/api/v1/clients/[^/]+/photo$"
        r"|^/api/v1/client-notes/[^/]+/attachments$"
        r"|^/api/v1/import-jobs/[^/]+/source$"
    )  # keep in step with the @upload matcher in infra/proxy/Caddyfile

    def __init__(self, app) -> None:
        self.app = app
        self.small = get_settings().api.max_body_bytes
        self.large = get_settings().storage.max_upload_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self.large if self.UPLOAD_PATHS.match(scope["path"]) else self.small
        declared = dict(scope["headers"]).get(b"content-length", b"")
        seen, refused = 0, declared.isdigit() and int(declared) > limit

        async def refuse() -> None:
            body = {
                "type": "/problems/payload-too-large", "title": "Payload too large", "status": 413,
                "code": "payload-too-large", "instance": scope["path"], "trace_id": context.request_id.get(),
                "detail": f"The request body may not exceed {limit} bytes.",
            }  # fmt: skip
            raw = json.dumps(body).encode()
            headers = [(b"content-type", b"application/problem+json"), (b"content-length", str(len(raw)).encode())]
            await send({"type": "http.response.start", "status": 413, "headers": headers})
            await send({"type": "http.response.body", "body": raw})

        if refused:
            return await refuse()

        async def counted():
            nonlocal seen, refused
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    refused = True
                    raise ValueError("request body over the limit")
            return message

        async def send_unless_refused(message) -> None:
            if not refused:  # whatever the framework makes of the aborted read is replaced by the 413 below
                await send(message)

        try:
            await self.app(scope, counted, send_unless_refused)
        except ValueError:
            if not refused:
                raise
        if refused:
            await refuse()


def _on_domain_error(request: Request, exc: DomainError):
    return problem(request, exc.status, exc.code, exc.detail, headers=exc.headers, **exc.extra)


def _on_validation_error(request: Request, exc: RequestValidationError):
    errors = [
        {
            "pointer": "/" + "/".join(str(part) for part in error["loc"][1:]),
            "code": error["type"],
            "detail": error["msg"],
        }
        for error in exc.errors()
    ]
    if any(error["code"] == CARD_DATA for error in errors):  # security-baseline 3: the client shows its own message
        return problem(request, 422, CARD_DATA, CARD_DATA_DETAIL, errors=errors)
    return problem(request, 422, "validation-failed", "The request is not valid.", errors=errors)


def _on_integrity_error(request: Request, exc: IntegrityError):
    """Database errors are mapped by constraint name (overview 3.13)."""
    diag = getattr(exc.orig, "diag", None)
    name = (diag.constraint_name if diag else None) or ""
    field = name.removeprefix(f"{name[:2]}_{diag.table_name}_") if diag and diag.table_name else name
    if diag and getattr(exc.orig, "sqlstate", None) == "23502":  # NOT NULL: a required field was sent as null
        field = diag.column_name
        errors = [{"pointer": f"/{field}", "code": "validation-failed", "detail": "This field cannot be null."}]
        return problem(request, 422, "validation-failed", f"{field} cannot be null.", errors=errors)
    field = CONSTRAINT_FIELDS.get(name, field)
    if name in CONSTRAINT_CODES:
        return problem(request, 409, CONSTRAINT_CODES[name])
    if name.startswith("uq_"):
        return problem(request, 409, "already-exists", f"A record with this {field} already exists.", field=field)
    if name.startswith(("ck_", "fk_")):
        detail = f"Invalid value for {field}."
        errors = [{"pointer": f"/{field}", "code": "validation-failed", "detail": detail}]
        return problem(request, 422, "validation-failed", detail, errors=errors)
    log.error("unmapped constraint %s", name, exc_info=exc)
    return problem(request, 500, "internal-error")


def _on_http_exception(request: Request, exc: StarletteHTTPException):
    codes = {401: "unauthenticated", 403: "permission-denied", 404: "not-found", 405: "method-not-allowed"}
    return problem(request, exc.status_code, codes.get(exc.status_code, "bad-request"), headers=exc.headers)


def _on_unhandled(request: Request, exc: Exception):
    log.error("unhandled error", exc_info=exc)
    return problem(request, 500, "internal-error")


def install(app: FastAPI) -> None:
    # Last added is outermost: the request id exists before a 413 is written, and every response gets headers.
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_exception_handler(DomainError, _on_domain_error)
    app.add_exception_handler(RequestValidationError, _on_validation_error)
    app.add_exception_handler(IntegrityError, _on_integrity_error)
    app.add_exception_handler(StarletteHTTPException, _on_http_exception)
    app.add_exception_handler(Exception, _on_unhandled)
