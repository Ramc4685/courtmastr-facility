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
    from app.modules.clients.router import router as clients_router
    from app.modules.platform.router import API_PREFIX, router
    from app.modules.programs.router import router as programs_router
    from app.modules.rentals.router import router as rentals_router
    from app.modules.resources.router import router as resources_router
    from app.modules.scheduling.router import router as scheduling_router

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
    for each in (resources_router, scheduling_router, programs_router):
        app.include_router(each, prefix=API_PREFIX)
    app.include_router(rentals_router, prefix=API_PREFIX)
    return app


app = create_app()
