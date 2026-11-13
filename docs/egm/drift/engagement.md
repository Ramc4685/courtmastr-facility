## backend/app/modules/engagement/README.md

- [contract] The README says the context's endpoints are the contract (lines 104-110), but `docs/api/openapi-programs.yaml` tags many operations `engagement` that no route serves, and Not built (lines 116-120) lists none of them. Evidence is the router (`router.py:37-479`) against the spec. Operations missing from the code:
  - `POST /webhooks/email/{provider}`. README deviation 6 (lines 80-82) says the webhook is not built, but this is not in Not built.
  - Campaign operations: `POST /campaigns/{id}/resume`, `/unschedule`, `/copy` and `/audience-preview`.
  - Media library: `GET|POST /media-assets` and `DELETE /media-assets/{id}`.
  - App content: `/news-stories` (and `/public/news-stories`), `/home-screens`, `/app-tiles`, `/portal-content*`, `/portal/content`, `/locations/{id}/app-content`, `/app-config`, `/public/app-config` and `/public/app-directory`.
  - Portal and public intake: `/portal-invitations*`, `/public/portal-invitations/*`, `/trial-requests*`, `/portal/favorites*`, `/portal/app-events`, `/portal/menu` and `/app-analytics`.
  - The email-verification routes in this spec file are served by `clients/router.py`, not engagement.
- [contract] The spec and the code disagree on the shape of some routes:
  - The spec has `POST /campaigns/{id}/test-send` (`openapi-programs.yaml:4633`); the code has `POST /campaigns/{id}/test` (`router.py:202`).
  - The spec has `GET|PUT /portal/communication-preferences` (`openapi-programs.yaml:~4196`); the code has `/portal/clients/{client_id}/communication-preferences` (`router.py:51,56`).
  - The spec has `POST /public/unsubscribe/{token}`; the code takes the token in the body at `POST /public/unsubscribe` (`router.py:457`), which matches README lines 27-29.
  - The spec names the device path parameter `device_id`; the code uses `device_registration_id` (`router.py:427`).
