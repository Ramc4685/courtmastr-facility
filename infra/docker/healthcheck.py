"""Container healthcheck: `healthcheck.py api | redis | db`. Exit 0 healthy, 1 not. Prints nothing a log must keep.

api   liveness over loopback (readiness, with its dependency checks, is what the proxy and monitors call)
redis the job broker is reachable (worker)
db    the platform role can run a query (relay, scheduler)
"""

import sys
import urllib.request


def main(kind: str) -> None:
    if kind == "api":
        urllib.request.urlopen("http://127.0.0.1:8100/api/v1/health/live", timeout=2).read()
    elif kind == "redis":
        from app.core.ratelimit import _redis

        _redis().ping()
    elif kind == "db":
        from sqlalchemy import text

        from app.core.db.platform import platform_engine

        with platform_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    else:
        raise SystemExit(f"unknown check {kind!r}")


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except SystemExit:
        raise
    except Exception:
        sys.exit(1)
