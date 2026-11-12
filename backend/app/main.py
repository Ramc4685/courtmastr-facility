"""API app factory."""

from fastapi import FastAPI

from app.bootstrap import bootstrap
from app.core import api, logging
from app.core.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    logging.configure()
    bootstrap()
    from app.modules.assessments.router import router as assessments_router
    from app.modules.billing.router import router as billing_router
    from app.modules.clients.router import public as clients_public
    from app.modules.clients.router import router as clients_router
    from app.modules.documents.router import public as documents_public
    from app.modules.documents.router import router as documents_router
    from app.modules.engagement.router import public as engagement_public
    from app.modules.engagement.router import router as engagement_router
    from app.modules.integrations.router import router as integrations_router
    from app.modules.leagues.router import router as leagues_router
    from app.modules.memberships.router import public as memberships_public
    from app.modules.memberships.router import router as memberships_router
    from app.modules.packages.router import public as packages_public
    from app.modules.packages.router import router as packages_router
    from app.modules.platform.files_router import router as files_router
    from app.modules.platform.privacy_router import router as privacy_router
    from app.modules.platform.router import API_PREFIX, router
    from app.modules.pos.router import router as pos_router
    from app.modules.programs.router import public as programs_public
    from app.modules.programs.router import router as programs_router
    from app.modules.rentals.router import router as rentals_router
    from app.modules.reporting.router import router as reporting_router
    from app.modules.resources.router import router as resources_router
    from app.modules.scheduling.router import router as scheduling_router
    from app.modules.staff.router import router as staff_router

    app = FastAPI(
        title=f"{settings.app.display_name} API",
        version="1.0.0",
        description=_API_DESCRIPTION,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    api.install(app)
    for each in (router, clients_router, billing_router, pos_router, documents_router):
        app.include_router(each, prefix=API_PREFIX)
    for each in (clients_public, engagement_router, engagement_public, privacy_router, documents_public):
        app.include_router(each, prefix=API_PREFIX)
    for each in (memberships_router, packages_router, memberships_public, packages_public):
        app.include_router(each, prefix=API_PREFIX)
    for each in (resources_router, scheduling_router, programs_router, programs_public):
        app.include_router(each, prefix=API_PREFIX)
    app.include_router(rentals_router, prefix=API_PREFIX)
    app.include_router(staff_router, prefix=API_PREFIX)
    app.include_router(assessments_router, prefix=API_PREFIX)
    from app.modules.access.router import kiosk as access_kiosk
    from app.modules.access.router import router as access_router

    for each in (access_router, access_kiosk):
        app.include_router(each, prefix=API_PREFIX)
    app.include_router(leagues_router, prefix=API_PREFIX)
    app.include_router(files_router, prefix=API_PREFIX)
    from app.modules.platform import entitlements_router
    from app.modules.platform.branding_router import router as branding_router
    from app.modules.platform.onboarding_router import router as onboarding_router

    for each in (entitlements_router.router, entitlements_router.operator, branding_router, onboarding_router):
        app.include_router(each, prefix=API_PREFIX)
    app.include_router(integrations_router, prefix=API_PREFIX)
    app.include_router(reporting_router, prefix=API_PREFIX)
    _document_auth(app)
    return app


_API_DESCRIPTION = (
    "Authenticate with `Authorization: Bearer <token>`: an API key (`fhk_...`, created under Settings > API keys) "
    "or a signed-in session token. API keys may call staff operations within their scopes and locations. "
    "See docs/api/public-api-guide.md for pagination, errors, idempotency and webhook signatures."
)


def _document_auth(app: FastAPI) -> None:
    """Add the bearer scheme to the generated document: routes authenticate in current_ctx, not through FastAPI
    security dependencies, so FastAPI would not emit it."""
    generate = app.openapi

    def openapi() -> dict:
        if app.openapi_schema is None:
            doc = generate()  # also caches itself in app.openapi_schema
            doc.setdefault("components", {})["securitySchemes"] = {
                "bearer": {"type": "http", "scheme": "bearer", "description": "API key (fhk_...) or session token"}
            }
            doc["security"] = [{"bearer": []}]
        return app.openapi_schema

    app.openapi = openapi


app = create_app()
