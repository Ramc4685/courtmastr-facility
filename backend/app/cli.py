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
    else:
        from app.bootstrap import bootstrap
        from app.modules.platform import service

        bootstrap()
        result = service.onboard_tenant(
            name=args.name, slug=args.slug, default_time_zone=args.time_zone, owner_email=args.owner_email,
            owner_first_name=args.owner_first_name, owner_last_name=args.owner_last_name,
        )  # fmt: skip
        print(json.dumps(result, default=str))


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
