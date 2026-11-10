"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}


def upgrade() -> None:
    # Every new tenant-owned table must call enable_rls("<table>") (append_only=True for ledgers and logs).
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
