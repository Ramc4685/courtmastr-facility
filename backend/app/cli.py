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
    else:
        from app.bootstrap import bootstrap
        from app.modules.platform import service

        bootstrap()
        result = service.onboard_tenant(
            name=args.name, slug=args.slug, default_time_zone=args.time_zone, owner_email=args.owner_email,
            owner_first_name=args.owner_first_name, owner_last_name=args.owner_last_name,
        )  # fmt: skip
        print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()
