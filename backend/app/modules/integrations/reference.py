"""The generated public API reference (INT-01): which operations an API key can call and with which scopes.

Derived from the routes themselves, so it cannot drift: an operation is open to keys when it is gated by
`require(<keys>)` and at least one of those keys may be given to a key (rbac-matrix section 11). Each such
operation gets `x-api-key-scopes` in the OpenAPI document; the integrations screen lists them.
"""

from typing import Any

from fastapi.routing import APIRoute

from app.core.auth.permissions import CATALOGUE

_METHODS = ("get", "post", "put", "patch", "delete")


def _walk(routes, prefix: str = ""):
    """(full path, route). FastAPI keeps include_router() lazy here, so descend by hand (as test_security)."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        elif hasattr(route, "original_router"):
            yield from _walk(route.original_router.routes, prefix + route.include_context.prefix)


def _gate_keys(dependant) -> tuple[str, ...] | None:
    if getattr(dependant.call, "accepts_api_key", False):
        return tuple(dependant.call.keys)
    for sub in dependant.dependencies:
        if (found := _gate_keys(sub)) is not None:
            return found
    return None


def key_scopes(route: APIRoute) -> list[str]:
    """The permission keys that open `route` to an API key; empty when no key can call it."""
    from app.modules.integrations.service import grantable_to_key

    keys = _gate_keys(route.dependant) or ()
    return [k for k in keys if k in CATALOGUE and grantable_to_key(CATALOGUE[k])]


def annotate(doc: dict[str, Any], routes) -> None:
    """Mark every operation an API key may call with `x-api-key-scopes` (called once when the document is built)."""
    for path, route in _walk(routes):
        scopes = key_scopes(route)
        operations = doc.get("paths", {}).get(path, {})
        for method in route.methods or ():
            operation = operations.get(method.lower())
            if scopes and operation is not None:
                operation["x-api-key-scopes"] = scopes


def operations(doc: dict[str, Any]) -> list[dict]:
    """The key-callable operations of an annotated document, sorted by path then method."""
    out = []
    for path, item in sorted(doc.get("paths", {}).items()):
        for method in _METHODS:
            operation = item.get(method)
            if operation and operation.get("x-api-key-scopes"):
                out.append({
                    "method": method.upper(), "path": path, "operation_id": operation.get("operationId", ""),
                    "summary": operation.get("summary", ""), "tag": (operation.get("tags") or [""])[0],
                    "scopes": operation["x-api-key-scopes"],
                })  # fmt: skip
    return out
