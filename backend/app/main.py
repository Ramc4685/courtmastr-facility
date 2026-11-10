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
    from app.modules.integrations.router import router as integrations_router
    from app.modules.platform.router import API_PREFIX, router

    app = FastAPI(
        title=f"{settings.app.display_name} API",
        version="1.0.0",
        description=_API_DESCRIPTION,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    api.install(app)
    for each in (router, clients_router, billing_router, integrations_router):
        app.include_router(each, prefix=API_PREFIX)
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
