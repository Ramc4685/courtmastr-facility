## backend/app/modules/documents/README.md

- [missing] Lines 25-26 say selling contexts "(memberships, packages, programs, rentals)" call `requirements_for` / `ensure_pending` / `consume`. Rentals calls none of them; the only callers are `backend/app/modules/memberships/service.py:467,594,600,602,729,768`, `backend/app/modules/packages/service.py:573,575,655,699` and `backend/app/modules/programs/checkout.py:54,135,139,164`. A rental type has no document gate.
