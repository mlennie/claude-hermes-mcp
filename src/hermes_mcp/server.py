"""FastMCP server exposing `hermes_ask` over Streamable HTTP.

Wraps the FastMCP Starlette app with bearer-token middleware and runs it
via uvicorn.
"""

from __future__ import annotations

import logging
from typing import Literal, cast

import uvicorn
from mcp.server.fastmcp import FastMCP

from .auth import BearerAuthMiddleware
from .config import Config
from .hermes_client import HermesClient, HermesError

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


def build_app(config: Config, client: HermesClient) -> tuple[FastMCP, BearerAuthMiddleware]:
    """Create a FastMCP server with the hermes_ask tool registered, wrapped
    in bearer auth middleware. Returns (mcp_instance, asgi_app).
    """
    mcp = FastMCP(
        "hermes-mcp",
        host=config.bind_host,
        port=config.bind_port,
        log_level=config.log_level,  # type: ignore[arg-type]
        stateless_http=False,
    )

    @mcp.tool(description=_TOOL_DESCRIPTION)
    def hermes_ask(
        prompt: str,
        session_id: str | None = None,
        toolsets: list[str] | None = None,
    ) -> str:
        try:
            return client.ask(prompt, session_id=session_id, toolsets=toolsets)
        except HermesError as exc:
            # Re-raise as ValueError so MCP returns a clean tool error to the client.
            raise ValueError(str(exc)) from exc

    starlette_app = mcp.streamable_http_app()
    wrapped = BearerAuthMiddleware(starlette_app, expected_token=config.bearer_token)
    return mcp, wrapped


def serve(config: Config, client: HermesClient) -> None:
    _, app = build_app(config, client)
    logger.info(
        "hermes-mcp listening on %s:%d (transport=streamable-http)",
        config.bind_host,
        config.bind_port,
    )
    _log_level = config.log_level.lower()
    uvicorn.run(
        app,
        host=config.bind_host,
        port=config.bind_port,
        log_level=cast(
            Literal["critical", "error", "warning", "info", "debug", "trace"],
            _log_level,
        ),
    )
