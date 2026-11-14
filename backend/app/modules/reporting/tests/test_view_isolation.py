"""Every reporting view (`rpt_*`, security_invoker) shows a tenant its own rows only: read from another tenant, each
one is empty, and read from the owner, no row carries another tenant's id. The list comes from the catalogue, so a
new view is covered without being named here."""

from sqlalchemy import text

from app.core.db.session import tenant_session
from conftest import make_tenant


def test_every_reporting_view_is_empty_to_another_tenant(two_tenants):
    a, _ = two_tenants
    stranger = make_tenant()
    with tenant_session(a.tenant.id) as session:
        views = session.scalars(text(
            "SELECT viewname FROM pg_views WHERE schemaname = 'public' AND viewname LIKE 'rpt\\_%' ORDER BY 1")).all()  # fmt: skip
        assert len(views) > 30
        seen = {v: session.scalar(text(f"SELECT count(*) FROM {v}")) for v in views}
        assert sum(seen.values()) > 0
        foreign = {v: session.scalar(text(f"SELECT count(*) FROM {v} WHERE tenant_id <> current_setting('app.tenant_id')::uuid"))
                   for v in views if session.scalar(text(
                       "SELECT count(*) FROM information_schema.columns WHERE table_name = :v AND column_name = 'tenant_id'"), {"v": v})}  # fmt: skip
        assert {v: n for v, n in foreign.items() if n} == {}
    with tenant_session(stranger.id) as session:
        leaked = {v: session.scalar(text(f"SELECT count(*) FROM {v}")) for v in views}
    assert {v: n for v, n in leaked.items() if n} == {}
