"""integrations context (build module 16): API keys, outbound webhooks, provider connections, the accounting
export and the adapter command log.

Public interface for routers, jobs and other contexts: `service` (internal functions `adapter_for`,
`video_meetings`) and `auth` (the API-key authenticator). Never import this package's models or schemas from
another context.
"""

from app.modules.integrations import auth, handlers, jobs, models, permissions, service

__all__ = ["auth", "handlers", "jobs", "models", "permissions", "service"]
