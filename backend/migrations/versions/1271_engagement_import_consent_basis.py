"""engagement: consent basis `import` (Phase 8 I1)

A marketing opt-in carried over by a CSV import outside GDPR mode has no proof of how it was given, so it is
recorded with basis `import`, which GDPR mode does not count as express (PLT-16).

Revision ID: 1271
Revises: 1270
"""
from alembic import op

revision = '1271'
down_revision = '1270'

_OLD = "'express', 'express_written', 'express_verbal', 'implied_purchase', 'implied_inquiry'"


def upgrade() -> None:
    op.drop_constraint(op.f('ck_consent_event_basis'), 'consent_event', type_='check')
    op.create_check_constraint(op.f('ck_consent_event_basis'), 'consent_event', f"basis IN ({_OLD}, 'import')")


def downgrade() -> None:
    # consent_event is append-only proof: rows with basis `import` are kept, so the old check is not validated.
    op.drop_constraint(op.f('ck_consent_event_basis'), 'consent_event', type_='check')
    op.execute(f"ALTER TABLE consent_event ADD CONSTRAINT ck_consent_event_basis CHECK (basis IN ({_OLD})) NOT VALID")
