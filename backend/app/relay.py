"""Outbox relay (overview 3.11): the one process that moves committed events to Dramatiq.

Runs as fh_platform because it reads every tenant's unpublished rows; the work itself happens in
@tenant_actor subscribers. Delivery is at-least-once: enqueue first, mark published in the same transaction.
"""

import logging
import time

from sqlalchemy import text

from app.bootstrap import bootstrap
from app.core.db.platform import platform_engine
from app.core.events import SUBSCRIBERS

log = logging.getLogger(__name__)
_CLAIM = text(
    "SELECT id, tenant_id, event_type, payload FROM outbox_event WHERE published_at IS NULL "
    "ORDER BY occurred_at LIMIT :limit FOR UPDATE SKIP LOCKED"
)
_MARK = text("UPDATE outbox_event SET published_at = now(), attempts = attempts + 1 WHERE id = ANY(:ids)")


def relay_once(limit: int = 200) -> int:
    with platform_engine().begin() as conn:
        rows = conn.execute(_CLAIM, {"limit": limit}).all()
        for row in rows:
            for actor in SUBSCRIBERS.get(row.event_type, ()):
                actor.send(str(row.tenant_id), str(row.id), row.payload)
        if rows:
            conn.execute(_MARK, {"ids": [row.id for row in rows]})
    return len(rows)


def main() -> None:  # pragma: no cover - a loop around relay_once
    from app.core import logging as app_logging

    app_logging.configure()
    bootstrap()
    log.info("outbox relay started")
    while True:
        if relay_once() == 0:
            time.sleep(1)


if __name__ == "__main__":  # pragma: no cover
    main()
