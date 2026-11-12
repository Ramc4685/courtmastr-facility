"""Logo routes (PLT-08). Uploads are raw image bytes with their Content-Type and an optional X-File-Name."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, public_session, request_session, require
from app.core.errors import NotFound
from app.core.schemas import Out
from app.modules.platform import branding, files

# No router-level idempotency: two routes are anonymous, and the rest are PUT/DELETE (idempotent by method).
router = APIRouter(route_class=TxRoute, tags=["platform"], generate_unique_id_function=camel_id)
TenantLogo = Depends(require("platform.tenant.update"))
LocationLogo = Depends(require("platform.location.update"))


class LocationLogoOut(Out):
    location_id: UUID
    logo_url: str


class BrandingOut(Out):
    tenant_logo_url: str | None
    locations: list[LocationLogoOut]


# The anonymous route answers with its own models (portal schemas never shared with staff routes).
class PublicLocationLogo(Out):
    location_id: UUID
    logo_url: str


class PublicBranding(Out):
    tenant_logo_url: str | None
    locations: list[PublicLocationLogo]


async def _upload(request: Request) -> tuple[bytes, str, str | None]:
    content_type = request.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
    return await request.body(), content_type, request.headers.get("x-file-name")


@router.get("/public/branding", response_model=PublicBranding)
def get_public_branding(session: Annotated[Session, Depends(public_session)]):
    """Logo URLs of the tenant resolved from the host: the staff shell and the member portal header."""
    return branding.branding(session)


@router.get("/public/objects/{object_key:path}", response_class=Response)
def get_public_object(object_key: str, request: Request):
    """Serves the public prefix t/<tenant>/public/<file> when no bucket or CDN origin is configured. Only logos."""
    parts = object_key.split("/")
    try:
        tenant_id, file_id = UUID(parts[1]), UUID(parts[3])
    except (IndexError, ValueError):
        raise NotFound() from None
    if parts != ["t", str(tenant_id), "public", str(file_id)]:
        raise NotFound()
    session = request_session(request, tenant_id)
    _, data = files.read(session, (row := branding.public_object(session, object_key)).id)
    return Response(
        data, media_type=row.content_type,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "public, max-age=86400",
                 "Content-Disposition": "inline"},
    )  # fmt: skip


@router.put("/branding/logo", response_model=BrandingOut)
async def put_tenant_logo(request: Request, ctx: Ctx = TenantLogo):
    """JPEG or PNG up to 512 KiB. Errors: file-type-mismatch, file-too-large, file-empty."""
    return branding.set_logo(ctx.session, ctx.principal, None, *await _upload(request))


@router.delete("/branding/logo", response_model=BrandingOut)
def delete_tenant_logo(ctx: Ctx = TenantLogo):
    return branding.remove_logo(ctx.session, ctx.principal, None)


@router.put("/locations/{location_id}/logo", response_model=BrandingOut)
async def put_location_logo(location_id: UUID, request: Request, ctx: Ctx = LocationLogo):
    """JPEG or PNG up to 512 KiB. Errors: file-type-mismatch, file-too-large, file-empty."""
    return branding.set_logo(ctx.session, ctx.principal, location_id, *await _upload(request))


@router.delete("/locations/{location_id}/logo", response_model=BrandingOut)
def delete_location_logo(location_id: UUID, ctx: Ctx = LocationLogo):
    return branding.remove_logo(ctx.session, ctx.principal, location_id)
