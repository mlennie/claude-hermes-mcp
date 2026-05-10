"""Entrypoint for the `hermes-mcp` console script and `python -m hermes_mcp`."""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__
from .config import Config, ConfigError, configure_logging
from .doctor import DoctorError, run_checks
from .hermes_client import HermesClient
from .oauth import mint_client_credentials
from .server import serve

logger = logging.getLogger("hermes_mcp")


def _mint_client() -> int:
    client_id, client_secret = mint_client_credentials()
    print("# Paste these into /etc/hermes-mcp.env (or your shell):")
    print(f"OAUTH_CLIENT_ID={client_id}")
    print(f"OAUTH_CLIENT_SECRET={client_secret}")
    print()
    print("# Then in Claude Desktop > Settings > Connectors > Add custom connector:")
    print("#   URL:           https://<your-tunnel-host>/mcp")
    print(f"#   Client ID:     {client_id}")
    print(f"#   Client Secret: {client_secret}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hermes-mcp",
        description="MCP bridge for delegating tasks from Claude to a local Hermes Agent.",
    )
    parser.add_argument("--version", action="version", version=f"hermes-mcp {__version__}")
    parser.add_argument(
        "command",
        nargs="?",
        default="serve",
        choices=("serve", "doctor", "mint-client"),
        help=(
            "serve (default): run the MCP server. "
            "doctor: run startup checks and exit. "
            "mint-client: print a fresh OAUTH_CLIENT_ID / OAUTH_CLIENT_SECRET pair."
        ),
    )
    args = parser.parse_args(argv)

    if args.command == "mint-client":
        return _mint_client()

    try:
        config = Config.from_env()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    configure_logging(config.log_level)

    try:
        result = run_checks(config)
    except DoctorError as exc:
        print(f"doctor: {exc}", file=sys.stderr)
        return 3

    if args.command == "doctor":
        print(f"hermes-mcp doctor: ok ({result.hermes_version})")
        return 0

    client = HermesClient(
        hermes_bin=result.hermes_path,
        timeout_seconds=config.hermes_timeout_seconds,
        default_toolsets=config.hermes_toolsets,
    )

    try:
        serve(config, client)
    except KeyboardInterrupt:
        logger.info("shutdown requested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
