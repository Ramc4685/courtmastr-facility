"""Backlog 26: every Idempotency-Key header is pattern-checked, so no route can feed a raw key to a provider query."""

from app.core.idempotency import KEY_PATTERN
from app.main import app


def test_every_idempotency_key_header_carries_the_pattern():
    seen, loose = 0, []
    for path, ops in app.openapi()["paths"].items():
        for verb, op in ops.items():
            for p in op.get("parameters", []):
                if p.get("in") == "header" and p["name"].lower() == "idempotency-key":
                    seen += 1
                    schema = p.get("schema", {})
                    patterns = [schema.get("pattern")] + [s.get("pattern") for s in schema.get("anyOf", [])]
                    if KEY_PATTERN not in patterns:
                        loose.append(f"{verb.upper()} {path}")
    assert seen > 20 and loose == []
