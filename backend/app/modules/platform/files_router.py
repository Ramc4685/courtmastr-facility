"""The local storage adapter's signed download route (security-baseline 8.3). Object-storage adapters hand out
presigned bucket URLs instead, so this route only serves when the bucket has no origin of its own. The URL's
signature is the credential: the permission check happened when `files.download_url` issued it."""

from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import request_session
from app.modules.platform import files

router = APIRouter(route_class=TxRoute, tags=["platform"], generate_unique_id_function=camel_id)


@router.get("/files/{tenant_id}/{file_id}", response_class=Response)
def get_signed_file(tenant_id: UUID, file_id: UUID, request: Request, exp: int = Query(0), sig: str = Query("")):
    # Missing or malformed signatures are 404 like a wrong one: the route reveals nothing without a valid URL.
    files.check_signature(tenant_id, file_id, exp, sig)
    row, data = files.read(request_session(request, tenant_id), file_id)
    return Response(
        data, media_type=row.content_type,
        headers={"Content-Disposition": files.disposition(row), "X-Content-Type-Options": "nosniff",
                 "Cache-Control": "private, no-store"},
    )  # fmt: skip
