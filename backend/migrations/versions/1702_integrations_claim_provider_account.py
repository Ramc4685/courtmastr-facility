"""integrations (Phase 15): app.claim_provider_account() registers a provider account for the current tenant and
says whether the tenant holds it, so a QuickBooks or Zoom company already routed to another tenant is refused
instead of passing silently (register_provider_account is ON CONFLICT DO NOTHING), and
app.release_provider_account(), which frees the current tenant's own claim on disconnect.

Revision ID: 1702
Revises: 1701
"""
from alembic import op


revision = '1702'
down_revision = '1701'


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION app.claim_provider_account(p_provider text, p_ref text) RETURNS boolean
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
            INSERT INTO public.provider_account_lookup (provider, provider_account_ref, tenant_id)
            VALUES (p_provider, p_ref, app.current_tenant_id())
            ON CONFLICT (provider, provider_account_ref) DO NOTHING;
            SELECT tenant_id = app.current_tenant_id() FROM public.provider_account_lookup
            WHERE provider = p_provider AND provider_account_ref = p_ref
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.claim_provider_account(text, text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.claim_provider_account(text, text) TO fh_app")
    # The release deletes only the current tenant's own claim, so no tenant can free another's account.
    op.execute(
        """
        CREATE FUNCTION app.release_provider_account(p_provider text, p_ref text) RETURNS void
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
            DELETE FROM public.provider_account_lookup
            WHERE provider = p_provider AND provider_account_ref = p_ref AND tenant_id = app.current_tenant_id()
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.release_provider_account(text, text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.release_provider_account(text, text) TO fh_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION app.release_provider_account(text, text)")
    op.execute("DROP FUNCTION app.claim_provider_account(text, text)")
