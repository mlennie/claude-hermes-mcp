"""Environment-variable configuration for hermes-mcp.

All knobs documented in `.env.example`. The server refuses to start if any
of OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, OAUTH_ISSUER_URL, or HERMES_API_KEY
is missing.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import Literal

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
_VALID_LOG_LEVELS: frozenset[str] = frozenset(("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"))


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


DEFAULT_OAUTH_ALLOWED_REDIRECT_SCHEMES: tuple[str, ...] = ("claude", "claudeai", "cursor")


@dataclass(frozen=True)
class Config:
    oauth_client_id: str
    oauth_client_secret: str
    oauth_issuer_url: str
    hermes_api_url: str
    hermes_api_key: str
    hermes_model: str
    hermes_request_timeout_seconds: int
    bind_host: str
    bind_port: int
    allowed_hosts: tuple[str, ...]
    allowed_redirect_schemes: tuple[str, ...]
    log_level: LogLevel

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Config:
        e = env if env is not None else os.environ

        client_id = (e.get("OAUTH_CLIENT_ID") or "").strip()
        if not client_id:
            raise ConfigError(
                "OAUTH_CLIENT_ID is required. Generate one with: hermes-mcp mint-client"
            )

        client_secret = (e.get("OAUTH_CLIENT_SECRET") or "").strip()
        if not client_secret:
            raise ConfigError(
                "OAUTH_CLIENT_SECRET is required. Generate one with: hermes-mcp mint-client"
            )
        if len(client_secret) < 32:
            raise ConfigError("OAUTH_CLIENT_SECRET must be at least 32 characters")

        issuer_url = (e.get("OAUTH_ISSUER_URL") or "").strip().rstrip("/")
        if not issuer_url:
            raise ConfigError(
                "OAUTH_ISSUER_URL is required (your public tunnel URL, "
                "e.g. https://hermes.example.com)"
            )
        if not (issuer_url.startswith("https://") or issuer_url.startswith("http://localhost")):
            raise ConfigError(
                f"OAUTH_ISSUER_URL must be HTTPS (or http://localhost for testing), got {issuer_url}"
            )

        hermes_api_url = (e.get("HERMES_API_URL") or "http://127.0.0.1:8642").strip().rstrip("/")
        if not (hermes_api_url.startswith("http://") or hermes_api_url.startswith("https://")):
            raise ConfigError(f"HERMES_API_URL must be http:// or https://, got {hermes_api_url}")

        hermes_api_key = (e.get("HERMES_API_KEY") or "").strip()
        if not hermes_api_key:
            raise ConfigError(
                "HERMES_API_KEY is required (the bearer token for the Hermes gateway "
                "OpenAI-compatible API; check ~/.hermes/.env for API_SERVER_KEY)."
            )

        hermes_model = (e.get("HERMES_MODEL") or "hermes-agent").strip()

        try:
            port = int(e.get("BIND_PORT", "8765"))
        except ValueError as exc:
            raise ConfigError(f"BIND_PORT must be an integer, got {e.get('BIND_PORT')!r}") from exc
        if not 1 <= port <= 65535:
            raise ConfigError(f"BIND_PORT must be in 1..65535, got {port}")

        try:
            request_timeout = int(e.get("HERMES_REQUEST_TIMEOUT_SECONDS", "300"))
        except ValueError as exc:
            raise ConfigError(
                "HERMES_REQUEST_TIMEOUT_SECONDS must be an integer, got "
                f"{e.get('HERMES_REQUEST_TIMEOUT_SECONDS')!r}"
            ) from exc
        if request_timeout <= 0:
            raise ConfigError(
                f"HERMES_REQUEST_TIMEOUT_SECONDS must be positive, got {request_timeout}"
            )

        allowed_hosts_raw = (e.get("MCP_ALLOWED_HOSTS") or "").strip()
        allowed_hosts = tuple(h.strip() for h in allowed_hosts_raw.split(",") if h.strip())

        # OAuth redirect-URI scheme allowlist. Each MCP client uses its own
        # custom URI scheme for the OAuth redirect (Claude → claude/claudeai,
        # Cursor → cursor, etc.). The default covers the clients we test
        # against; operators add to it for new clients.
        schemes_raw = (e.get("OAUTH_ALLOWED_REDIRECT_SCHEMES") or "").strip()
        if schemes_raw:
            allowed_redirect_schemes = tuple(
                s.strip().lower() for s in schemes_raw.split(",") if s.strip()
            )
        else:
            allowed_redirect_schemes = DEFAULT_OAUTH_ALLOWED_REDIRECT_SCHEMES

        log_level_raw = (e.get("LOG_LEVEL") or "INFO").upper()
        if log_level_raw not in _VALID_LOG_LEVELS:
            raise ConfigError(
                f"LOG_LEVEL must be one of DEBUG/INFO/WARNING/ERROR/CRITICAL, got {log_level_raw}"
            )
        log_level: LogLevel = log_level_raw  # type: ignore[assignment]

        bind_host = (e.get("BIND_HOST") or "127.0.0.1").strip()
        if bind_host not in ("127.0.0.1", "::1", "localhost"):
            logger = logging.getLogger(__name__)
            logger.warning(
                "BIND_HOST=%r is not loopback. The bridge expects a tunnel "
                "to reach it on localhost; binding elsewhere exposes the "
                "OAuth and tool endpoints to anyone who can reach this host.",
                bind_host,
            )

        return cls(
            oauth_client_id=client_id,
            oauth_client_secret=client_secret,
            oauth_issuer_url=issuer_url,
            hermes_api_url=hermes_api_url,
            hermes_api_key=hermes_api_key,
            hermes_model=hermes_model,
            hermes_request_timeout_seconds=request_timeout,
            bind_host=bind_host,
            bind_port=port,
            allowed_hosts=allowed_hosts,
            allowed_redirect_schemes=allowed_redirect_schemes,
            log_level=log_level,
        )


def configure_logging(level: LogLevel) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
