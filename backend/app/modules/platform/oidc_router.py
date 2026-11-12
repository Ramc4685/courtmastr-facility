"""OIDC sign-in routes (Phase 8 S3): the "Continue with" round trip, OIDC step-up, and the provider settings."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field, StringConstraints

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, cookie_parts, current_ctx, pre_session_cookie, require
from app.core.idempotency import idempotency
from app.core.pagination import ListQuery, list_query
from app.core.ratelimit import rate_limit
from app.core.schemas import In, Out, Page
from app.modules.platform import oidc
from app.modules.platform.router import PublicSession, _guarded, _sign_in_out, _token_session
from app.modules.platform.schemas import AuthSessionOut, MfaChallengeOut

public = APIRouter(route_class=TxRoute, tags=["platform"], generate_unique_id_function=camel_id)
me = APIRouter(route_class=TxRoute, tags=["platform"], generate_unique_id_function=camel_id)
admin = APIRouter(
    route_class=TxRoute, tags=["platform"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
Manage = Annotated[Ctx, Depends(require("platform.security.manage"))]  # read: Owner and Admin
OwnerManage = Annotated[Ctx, Depends(require("platform.identity_provider.manage"))]  # change: Owner only
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Url = Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=500)]
Secret = Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class SignInProvider(Out):
    id: UUID
    display_name: str
    preset: str


class OidcAuthorizeRequest(In):
    provider_id: UUID


class OidcAuthorizeOut(Out):
    authorization_url: str


class OidcCallbackRequest(In):
    state: Annotated[str, StringConstraints(max_length=200)]
    code: Annotated[str, StringConstraints(max_length=4000)]


class OidcLinkPendingOut(Out):
    link_pending: Literal[True] = True
    display_name: str = Field(description="The provider whose sign-in waits for the emailed confirmation.")


class OidcLinkConfirmRequest(In):
    token: Annotated[str, StringConstraints(max_length=200)]


class OidcLinkConfirmOut(Out):
    display_name: str


class IdentityProviderOut(Out):
    id: UUID
    preset: str
    display_name: str
    issuer_url: str
    client_id: str
    has_client_secret: bool
    scopes: list[str]
    allowed_email_domains: list[str]
    asserts_mfa: bool
    is_enabled: bool
    redirect_uri: str = Field(description="Register exactly this URI with the provider.")
    created_at: datetime
    updated_at: datetime


class IdentityProviderCreate(In):
    preset: Literal["google", "microsoft", "generic"]
    display_name: Text
    issuer_url: Url | None = Field(None, description="Optional for Google (https://accounts.google.com).")
    client_id: Text
    client_secret: Secret
    scopes: list[Text] | None = Field(None, max_length=20)
    allowed_email_domains: list[Text] = Field(default_factory=list, max_length=50)
    asserts_mfa: bool = False
    is_enabled: bool = True


class IdentityProviderUpdate(In):
    """The issuer and preset are fixed: links are keyed by issuer. Leave client_secret out to keep it."""

    display_name: Text | None = None
    client_id: Text | None = None
    client_secret: Secret | None = None
    scopes: list[Text] | None = Field(None, max_length=20)
    allowed_email_domains: list[Text] | None = Field(None, max_length=50)
    asserts_mfa: bool | None = None
    is_enabled: bool | None = None


# --- anonymous: the sign-in round trip -----------------------------------------------------------------------------


@public.get("/auth/oidc/providers", response_model=list[SignInProvider])
def list_sign_in_providers(session: PublicSession):
    """The tenant's enabled staff sign-in providers, for "Continue with" buttons. Tenant from host or slug."""
    return oidc.list_sign_in_providers(session)


@public.post("/auth/oidc/authorize", dependencies=_guarded("oidc"), response_model=OidcAuthorizeOut)
def start_oidc_sign_in(body: OidcAuthorizeRequest, request: Request, session: PublicSession):
    """Begin a sign-in at the provider: navigate the browser to authorization_url. Bound to this browser's
    pre-session cookie. Errors: not-found, csrf-failed, oidc-unavailable, rate-limited."""
    pre = request.cookies.get(pre_session_cookie())
    return {"authorization_url": oidc.start_sign_in(session, provider_id=body.provider_id, pre_session=pre)}


@public.post(
    "/auth/oidc/callback", dependencies=_guarded("oidc"),
    response_model=AuthSessionOut | MfaChallengeOut | OidcLinkPendingOut, response_model_exclude_none=True,
    responses={202: {"model": MfaChallengeOut, "description": "An MFA challenge, or (link_pending) a first sign-in "
                     "waiting for the emailed confirmation"}},
)  # fmt: skip
def complete_oidc_sign_in(body: OidcCallbackRequest, request: Request, response: Response):
    """Finish the round trip with the provider's code and state: a session, 202 with an MFA challenge, or (for a
    step-up round trip) the rotated session. A provider account not linked yet answers 202 link_pending,
    whether or not anyone matched; the matched user gets an email. Errors: oidc-failed, oidc-sign-in-refused,
    ip-not-allowed, oidc-reauthentication-stale, step-up-needs-code, csrf-failed, rate-limited."""
    session = _token_session(request, body.state, oidc.STATE_PREFIX, "oidc-failed")
    result = oidc.complete(
        session, state=body.state, code=body.code, pre_session=request.cookies.get(pre_session_cookie()),
        session_token=cookie_parts(request)[0],
    )  # fmt: skip
    if isinstance(result, oidc.LinkPending):
        response.status_code = 202
        return {"link_pending": True, "display_name": result.display_name}
    return _sign_in_out(result, response)


@public.post("/auth/oidc/link", dependencies=_guarded("consume"), response_model=OidcLinkConfirmOut)
def confirm_oidc_link(body: OidcLinkConfirmRequest, request: Request):
    """Redeem the emailed link that connects a provider account to the user's own (a first sign-in), in the
    browser that did that sign-in. No session starts. Errors: token-invalid, oidc-link-other-browser, csrf-failed."""
    session = _token_session(request, body.token, "fhl", "token-invalid")
    config = oidc.confirm_link(session, token=body.token, pre_session=request.cookies.get(pre_session_cookie()))
    return {"display_name": config.display_name}


# --- signed in: step-up at the provider -----------------------------------------------------------------------------


@me.post("/auth/oidc/step-up", dependencies=[Depends(rate_limit("step-up"))], response_model=OidcAuthorizeOut)
def start_oidc_step_up(request: Request, ctx: Ctx = Depends(current_ctx)):
    """Re-authenticate at the caller's linked provider (prompt=login, max_age=0); the callback rotates the
    session like /auth/step-up. Web staff sessions only. Errors: oidc-step-up-unavailable, oidc-unavailable."""
    pre = request.cookies.get(pre_session_cookie())
    return {"authorization_url": oidc.start_step_up(ctx.session, ctx.principal, pre_session=pre)}


# --- provider settings ---------------------------------------------------------------------------------------------


@admin.get("/identity-providers", response_model=Page[IdentityProviderOut])
def list_identity_providers(query: Annotated[ListQuery, Depends(list_query)], ctx: Manage):
    """The tenant's OIDC providers. Sort: display_name, created_at. The client secret is never returned."""
    return oidc.list_providers(ctx.session, ctx.principal, query)


@admin.post("/identity-providers", response_model=IdentityProviderOut, status_code=201)
def create_identity_provider(body: IdentityProviderCreate, ctx: OwnerManage):
    """Add a provider; its discovery document is fetched to check the issuer. Errors: oidc-issuer-invalid,
    oidc-discovery-failed, url-not-allowed, already-exists, step-up-required. Owner only."""
    return oidc.create_provider(ctx.session, ctx.principal, body.model_dump())


@admin.get("/identity-providers/{identity_provider_id}", response_model=IdentityProviderOut)
def get_identity_provider(identity_provider_id: UUID, ctx: Manage):
    return oidc.get_provider(ctx.session, ctx.principal, identity_provider_id)


@admin.patch("/identity-providers/{identity_provider_id}", response_model=IdentityProviderOut)
def update_identity_provider(identity_provider_id: UUID, body: IdentityProviderUpdate, ctx: OwnerManage):
    return oidc.update_provider(ctx.session, ctx.principal, identity_provider_id, body.model_dump(exclude_unset=True))


@admin.delete("/identity-providers/{identity_provider_id}", status_code=204)
def delete_identity_provider(identity_provider_id: UUID, ctx: OwnerManage) -> None:
    """Remove a provider. Staff linked to it sign in another way; adding it back restores their links."""
    oidc.delete_provider(ctx.session, ctx.principal, identity_provider_id)


router = APIRouter()
for part in (public, me, admin):
    router.include_router(part)
