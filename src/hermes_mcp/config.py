"""Environment-variable configuration for hermes-mcp.

All knobs documented in `.env.example`. The server refuses to start if any
of OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, or OAUTH_ISSUER_URL is missing.
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


@dataclass(frozen=True)
class Config:
    oauth_client_id: str
    oauth_client_secret: str
    oauth_issuer_url: str
    hermes_bin: str
    bind_host: str
    bind_port: int
    hermes_timeout_seconds: int
    hermes_toolsets: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
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

        try:
            port = int(e.get("BIND_PORT", "8765"))
        except ValueError as exc:
            raise ConfigError(f"BIND_PORT must be an integer, got {e.get('BIND_PORT')!r}") from exc
        if not 1 <= port <= 65535:
            raise ConfigError(f"BIND_PORT must be in 1..65535, got {port}")

        try:
            timeout = int(e.get("HERMES_TIMEOUT_SECONDS", "300"))
        except ValueError as exc:
            raise ConfigError(
                f"HERMES_TIMEOUT_SECONDS must be an integer, got {e.get('HERMES_TIMEOUT_SECONDS')!r}"
            ) from exc
        if timeout <= 0:
            raise ConfigError(f"HERMES_TIMEOUT_SECONDS must be positive, got {timeout}")

        toolsets_raw = (e.get("HERMES_TOOLSETS") or "").strip()
        toolsets = tuple(t.strip() for t in toolsets_raw.split(",") if t.strip())

        allowed_hosts_raw = (e.get("MCP_ALLOWED_HOSTS") or "").strip()
        allowed_hosts = tuple(h.strip() for h in allowed_hosts_raw.split(",") if h.strip())

        log_level_raw = (e.get("LOG_LEVEL") or "INFO").upper()
        if log_level_raw not in _VALID_LOG_LEVELS:
            raise ConfigError(
                f"LOG_LEVEL must be one of DEBUG/INFO/WARNING/ERROR/CRITICAL, got {log_level_raw}"
            )
        log_level: LogLevel = log_level_raw  # type: ignore[assignment]

        return cls(
            oauth_client_id=client_id,
            oauth_client_secret=client_secret,
            oauth_issuer_url=issuer_url,
            hermes_bin=(e.get("HERMES_BIN") or "hermes").strip(),
            bind_host=(e.get("BIND_HOST") or "127.0.0.1").strip(),
            bind_port=port,
            hermes_timeout_seconds=timeout,
            hermes_toolsets=toolsets,
            allowed_hosts=allowed_hosts,
            log_level=log_level,
        )


def configure_logging(level: LogLevel) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
