"""Alembic runs as fh_owner: one linear history, schema changes only (ADR 0001 section 4)."""

from alembic import context
from sqlalchemy import create_engine

import app.core.audit  # noqa: F401  (table definitions)
import app.core.events  # noqa: F401
import app.core.idempotency  # noqa: F401
import app.modules.billing.models  # noqa: F401
import app.modules.clients.models  # noqa: F401
import app.modules.platform.models  # noqa: F401
from app.core.db import Base
from app.core.settings import get_settings

engine = create_engine(get_settings().db_url("owner"))
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
