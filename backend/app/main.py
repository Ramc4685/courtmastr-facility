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
    from app.modules.engagement.router import router as engagement_router
    from app.modules.platform.privacy_router import router as privacy_router
    from app.modules.platform.router import API_PREFIX, router

    app = FastAPI(
        title=f"{settings.app.display_name} API",
        version="1.0.0",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    api.install(app)
    for each in (router, clients_router, billing_router):
        app.include_router(each, prefix=API_PREFIX)
    for each in (clients_public, engagement_router, privacy_router):
        app.include_router(each, prefix=API_PREFIX)
    return app


app = create_app()
