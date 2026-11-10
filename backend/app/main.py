"""API app factory."""

from fastapi import FastAPI

from app.bootstrap import bootstrap
from app.core import api, logging
from app.core.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    logging.configure()
    bootstrap()
    from app.modules.billing.router import router as billing_router
    from app.modules.clients.router import public as clients_public
    from app.modules.clients.router import router as clients_router
    from app.modules.documents.router import public as documents_public
    from app.modules.documents.router import router as documents_router
    from app.modules.engagement.router import router as engagement_router
    from app.modules.memberships.router import public as memberships_public
    from app.modules.memberships.router import router as memberships_router
    from app.modules.packages.router import public as packages_public
    from app.modules.packages.router import router as packages_router
    from app.modules.platform.privacy_router import router as privacy_router
    from app.modules.platform.router import API_PREFIX, router
    from app.modules.pos.router import router as pos_router

    app = FastAPI(
        title=f"{settings.app.display_name} API",
        version="1.0.0",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    api.install(app)
    for each in (router, clients_router, billing_router, pos_router, documents_router):
        app.include_router(each, prefix=API_PREFIX)
    for each in (clients_public, engagement_router, privacy_router, documents_public):
        app.include_router(each, prefix=API_PREFIX)
    for each in (memberships_router, packages_router, memberships_public, packages_public):
        app.include_router(each, prefix=API_PREFIX)
    return app


app = create_app()
