"""FastMCP server exposing `hermes_ask` over Streamable HTTP, gated by OAuth 2.1.

`build_app()` constructs a FastMCP instance wired up with our static-client
OAuth provider. FastMCP itself adds the bearer-validation middleware and the
authorization endpoints (`/authorize`, `/token`, `/.well-known/...`).
"""

from __future__ import annotations

import logging
from typing import Literal

import uvicorn
from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl

from .config import Config, LogLevel
from .hermes_client import HermesClient
from .oauth import StaticClientProvider

UvicornLogLevel = Literal["critical", "error", "warning", "info", "debug"]
_UVICORN_LEVELS: dict[LogLevel, UvicornLogLevel] = {
    "DEBUG": "debug",
    "INFO": "info",
    "WARNING": "warning",
    "ERROR": "error",
    "CRITICAL": "critical",
}


def _uvicorn_log_level(level: LogLevel) -> UvicornLogLevel:
    return _UVICORN_LEVELS[level]


logger = logging.getLogger(__name__)

_TOOL_DESCRIPTION = """\
Delegate a task to Hermes Agent on this user's mini-PC.

Use this when the user asks for things Claude cannot do directly itself:
  - Scheduling cron jobs / recurring tasks
  - Browser-driven web search and scraping
  - Sending email
  - Creating, saving, or editing local documents
  - Anything that should persist after this chat ends (Hermes memory, skills)
  - Sending WhatsApp / Slack messages via Hermes's messaging gateway

Args:
  prompt: Natural-language instruction for Hermes.
  session_id: Optional. Pass the same id across multiple calls in one chat
    to let Hermes remember prior steps (e.g. draft -> refine -> save).
  toolsets: Optional. Restrict Hermes to specific toolsets for this call.

Returns:
  Hermes's final answer text.
"""


def _build_transport_security(config: Config) -> TransportSecuritySettings:
    """Allowed-host list passed to FastMCP. Always includes localhost so the
    `hermes-mcp doctor` flow and curl smoke tests still work; appends any
    user-supplied hostnames (typically the public tunnel domain).
    """
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*", *config.allowed_hosts]
    origins = [
        "http://127.0.0.1:*",
        "http://localhost:*",
        "http://[::1]:*",
        *(f"https://{h}" for h in config.allowed_hosts if "://" not in h),
        *(h for h in config.allowed_hosts if "://" in h),
    ]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


def build_app(config: Config, client: HermesClient) -> FastMCP:
    """Create a FastMCP server with the hermes_ask tool and OAuth wired up."""
    provider = StaticClientProvider(
        client_id=config.oauth_client_id,
        client_secret=config.oauth_client_secret,
    )

    issuer_url = AnyHttpUrl(config.oauth_issuer_url)
    resource_server_url = AnyHttpUrl(f"{config.oauth_issuer_url}/mcp")

    mcp: FastMCP = FastMCP(
        "hermes-mcp",
        host=config.bind_host,
        port=config.bind_port,
        log_level=config.log_level,
        stateless_http=False,
        auth_server_provider=provider,
        auth=AuthSettings(
            issuer_url=issuer_url,
            resource_server_url=resource_server_url,
            client_registration_options=ClientRegistrationOptions(enabled=False),
            revocation_options=RevocationOptions(enabled=False),
        ),
        transport_security=_build_transport_security(config),
    )

    @mcp.tool(description=_TOOL_DESCRIPTION)
    def hermes_ask(
        prompt: str,
        session_id: str | None = None,
        toolsets: list[str] | None = None,
    ) -> str:
        # HermesError propagates; FastMCP wraps any Exception in ToolError.
        return client.ask(prompt, session_id=session_id, toolsets=toolsets)

    return mcp


def serve(config: Config, client: HermesClient) -> None:
    mcp = build_app(config, client)
    logger.info(
        "hermes-mcp listening on %s:%d (transport=streamable-http, oauth issuer=%s)",
        config.bind_host,
        config.bind_port,
        config.oauth_issuer_url,
    )
    uvicorn.run(
        mcp.streamable_http_app(),
        host=config.bind_host,
        port=config.bind_port,
        log_level=_uvicorn_log_level(config.log_level),
    )
