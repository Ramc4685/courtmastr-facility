"""Idempotency-Key handling for POST commands (overview 3.12).

begin() claims the key in its own short transaction; the stored response is written by complete() in the
handler's transaction, so "handled" and "remembered" commit together.
"""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy import Index, UniqueConstraint, delete, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core import clock
from app.core.auth.deps import Ctx, current_ctx
from app.core.db.base import Base, TenantOwned, tenant_args
from app.core.db.session import tenant_session
from app.core.errors import Conflict, ValidationFailed
from app.core.ids import new_id

_TTL = timedelta(hours=24)
# The key reaches provider queries (Stripe Search) and logs, so only a plain token alphabet is accepted.
KEY_PATTERN = r"^[A-Za-z0-9_.:\-]{1,255}$"


class IdempotencyKey(TenantOwned, Base):
    __tablename__ = "idempotency_key"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "scope", "key", name="uq_idempotency_key_tenant_scope_key"),
        Index("ix_idempotency_key_expiry", "expires_at"),
    )

    scope: Mapped[str]  # principal id plus route template
    key: Mapped[str]
    request_hash: Mapped[str]
    status: Mapped[str]  # in_progress | completed
    response_status: Mapped[int | None]
    response_body: Mapped[Any | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    expires_at: Mapped[datetime]


def secret_response(endpoint):
    """Route decorator, placed below @router.post: the response carries a secret, so it is never stored, and a
    replay of the key gets 409 instead of the body (no plaintext at rest, no ungated re-read)."""
    endpoint.secret_response = True
    return endpoint


def is_secret(request: Request) -> bool:
    return getattr(request.scope["route"].endpoint, "secret_response", False)


class Replay(Exception):
    """Raised to short-circuit a request whose key already completed; TxRoute returns the stored response."""

    def __init__(self, status: int, body: Any) -> None:
        self.status, self.body = status, body


def _match(scope: str, key: str):
    return (IdempotencyKey.scope == scope) & (IdempotencyKey.key == key)


def begin(tenant_id: UUID, scope: str, key: str, request_hash: str) -> tuple[int, Any] | None:
    """Claim the key. None = proceed; (status, body) = replay. A concurrent duplicate blocks on the unique
    index until the first claim commits, then sees in_progress."""
    now = clock.now()
    with tenant_session(tenant_id) as session:
        session.execute(delete(IdempotencyKey).where(_match(scope, key), IdempotencyKey.expires_at <= now))
        claimed = session.execute(
            pg_insert(IdempotencyKey)
            .values(
                id=new_id(),
                tenant_id=tenant_id,
                scope=scope,
                key=key,
                request_hash=request_hash,
                status="in_progress",
                expires_at=now + _TTL,
            )  # fmt: skip
            .on_conflict_do_nothing(constraint="uq_idempotency_key_tenant_scope_key")
            .returning(IdempotencyKey.id)
        ).first()
        if claimed:
            return None
        row = session.execute(select(IdempotencyKey).where(_match(scope, key))).scalar_one()
        if row.request_hash != request_hash:
            raise ValidationFailed(
                "This Idempotency-Key was used with a different request.", code="idempotency-key-reused"
            )
        if row.status != "completed":
            raise Conflict("The original request is still being processed.", code="request-in-progress")
        return row.response_status, row.response_body


def complete(session: Session, scope: str, key: str, status: int, body: Any) -> None:
    session.execute(
        update(IdempotencyKey)
        .where(_match(scope, key))
        .values(status="completed", response_status=status, response_body=body)
    )


def abandon(tenant_id: UUID, scope: str, key: str) -> None:
    """The handler failed and rolled back, so nothing happened: release the key for a retry."""
    with tenant_session(tenant_id) as session:
        session.execute(delete(IdempotencyKey).where(_match(scope, key), IdempotencyKey.status == "in_progress"))


def idempotency(
    request: Request,
    ctx: Ctx = Depends(current_ctx),
    idempotency_key: str | None = Header(None, pattern=KEY_PATTERN, description="Optional; keys live 24 hours."),
) -> None:
    """Router-level dependency: every POST that carries Idempotency-Key becomes replay-safe."""
    if idempotency_key is None or request.method != "POST":
        return
    scope = f"{ctx.principal.actor_id}:{request.scope['route'].path}"
    stored = begin(ctx.principal.tenant_id, scope, idempotency_key, request.state.body_hash)
    if stored is not None:
        if is_secret(request):
            raise Conflict("This request was already handled; its response is not kept.", code="response-not-stored")
        raise Replay(*stored)
    request.state.idempotency = (scope, idempotency_key)  # only once claimed, so only our own claim is released
