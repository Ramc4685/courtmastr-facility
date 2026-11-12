"""Developer commands: `python -m app.cli serve | openapi | onboard-tenant ...`."""

import argparse
import json
import sys

from app.core.settings import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run the API with reload")
    commands.add_parser("openapi", help="print the generated OpenAPI document")
    commands.add_parser("lane-db", help="create the databases named by FH_DB_NAME / FH_TEST_DB_NAME if missing")
    onboard = commands.add_parser("onboard-tenant", help="create a tenant and its owner (invite link is emailed)")
    for flag in ("name", "slug", "time-zone", "owner-email", "owner-first-name", "owner-last-name"):
        onboard.add_argument(f"--{flag}", required=True)
    failed = commands.add_parser("failed-jobs", help="list a tenant's dead letters, or requeue or discard one")
    failed.add_argument("--tenant", required=True, help="tenant id")
    action = failed.add_mutually_exclusive_group()
    action.add_argument("--requeue", metavar="FAILED_JOB_ID")
    action.add_argument("--discard", metavar="FAILED_JOB_ID")
    run_import = commands.add_parser("run-import", help="run an import job's chunks in this process (no worker)")
    run_import.add_argument("--tenant", required=True, help="tenant id")
    run_import.add_argument("--job", required=True, help="import job id")
    clear = commands.add_parser("clear-ip-allowlist", help="break-glass: empty a tenant's staff IP allow-list")
    clear.add_argument("--tenant", required=True, help="tenant id")
    args = parser.parse_args()

    if args.command == "serve":
        import uvicorn

        api = get_settings().api
        uvicorn.run("app.main:app", host=api.host, port=api.port, reload=get_settings().env == "dev")
    elif args.command == "openapi":
        from app.main import app

        json.dump(app.openapi(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    elif args.command == "lane-db":
        _create_lane_databases()
    elif args.command == "failed-jobs":
        _failed_jobs(args)
    elif args.command == "run-import":
        _run_import(args)
    elif args.command == "clear-ip-allowlist":
        _clear_ip_allowlist(args.tenant)
    else:
        from app.bootstrap import bootstrap
        from app.modules.platform import service

        bootstrap()
        result = service.onboard_tenant(
            name=args.name, slug=args.slug, default_time_zone=args.time_zone, owner_email=args.owner_email,
            owner_first_name=args.owner_first_name, owner_last_name=args.owner_last_name,
        )  # fmt: skip
        print(json.dumps(result, default=str))


def _failed_jobs(args) -> None:
    """ADR 0008 section 7, operator command. Runs as fh_app inside the tenant, as the system principal."""
    from uuid import UUID

    from app.bootstrap import bootstrap
    from app.core.auth import system_principal
    from app.core.db.session import tenant_session
    from app.modules.platform import retention
    from app.modules.platform.models import FailedJobResolution

    bootstrap()
    with tenant_session(UUID(args.tenant), actor=system_principal("operator-cli")) as session:
        if args.requeue or args.discard:
            resolution = FailedJobResolution.REQUEUED if args.requeue else FailedJobResolution.DISCARDED
            rows = [retention.resolve_failed_job(session, UUID(args.requeue or args.discard), resolution)]
        else:
            rows = retention.open_failed_jobs(session)
        for row in rows:
            print(json.dumps({k: getattr(row, k) for k in ("id", "actor_name", "queue", "args", "error_class",
                              "error_detail", "attempts", "failed_at", "resolution")}, default=str))  # fmt: skip


def _run_import(args) -> None:
    """Operator and lane command: finish an import job's current dry run or commit here, one transaction per
    chunk, as the queued `run_import` actor would (a worker that picks up the queued message later finds nothing
    left to do)."""
    from uuid import UUID

    from app.bootstrap import bootstrap
    from app.core.auth import system_principal
    from app.core.db.session import tenant_session
    from app.modules import imports

    bootstrap()
    more = True
    while more:
        with tenant_session(UUID(args.tenant), actor=system_principal("run_import")) as session:
            more = imports.service.run_chunk(session, UUID(args.job))


def _clear_ip_allowlist(tenant_id: str) -> None:
    """Operator break-glass (PLT-07): no role bypasses the allow-list, so a tenant that locks itself out is
    let back in from here. Audited as the system principal `operator-cli`."""
    from uuid import UUID

    from app.bootstrap import bootstrap
    from app.core.auth import system_principal
    from app.core.db.session import tenant_session
    from app.modules.platform import service

    bootstrap()
    operator = system_principal("operator-cli")
    with tenant_session(UUID(tenant_id), actor=operator) as session:
        removed = service.clear_staff_ip_allowlist(session, operator)
    print(json.dumps({"tenant_id": tenant_id, "removed": removed}))


def _create_lane_databases() -> None:
    """Same shape as infra/postgres/init: owned by fh_owner; roles are cluster-wide and grants come from the
    migrations. Connects as the local superuser, which only exists in development."""
    import os

    import psycopg
    from psycopg import sql

    db = get_settings().db
    names = [db.name, os.environ.get("FH_TEST_DB_NAME", "facilityhub_test")]
    with psycopg.connect(
        host=db.host, port=db.port, user="postgres", password=os.environ["FH_POSTGRES_PASSWORD"], dbname="postgres",
        autocommit=True,
    ) as conn:  # fmt: skip
        for name in names:
            if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
                print(f"database {name} exists")
            else:
                conn.execute(sql.SQL("CREATE DATABASE {} OWNER fh_owner").format(sql.Identifier(name)))
                print(f"database {name} created")


if __name__ == "__main__":
    main()
