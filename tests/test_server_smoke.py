"""Smoke test: build the FastMCP server, confirm hermes_ask is registered,
and confirm the tool works when the underlying HermesClient is mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hermes_mcp.config import Config
from hermes_mcp.hermes_client import HermesError
from hermes_mcp.server import build_app

VALID_ENV: dict[str, str] = {
    "OAUTH_CLIENT_ID": "hermes-mcp-test",
    "OAUTH_CLIENT_SECRET": "x" * 32,
    "OAUTH_ISSUER_URL": "https://hermes.example.com",
    "HERMES_API_KEY": "k" * 32,
}


def _config() -> Config:
    return Config.from_env(VALID_ENV)


def test_build_app_registers_hermes_ask() -> None:
    cfg = _config()
    client = MagicMock()
    mcp = build_app(cfg, client)
    tool_names = {t.name for t in mcp._tool_manager.list_tools()}
    assert "hermes_ask" in tool_names


def test_hermes_ask_invokes_client() -> None:
    cfg = _config()
    client = MagicMock()
    client.ask.return_value = "the answer"
    mcp = build_app(cfg, client)
    tool = mcp._tool_manager.get_tool("hermes_ask")
    assert tool is not None
    fn = tool.fn
    result = fn(prompt="hi", session_id=None, toolsets=None)
    assert result == "the answer"
    client.ask.assert_called_once_with("hi", session_id=None, toolsets=None)


def test_hermes_ask_propagates_hermes_error() -> None:
    cfg = _config()
    client = MagicMock()
    client.ask.side_effect = HermesError("hermes exited 2: boom")
    mcp = build_app(cfg, client)
    tool = mcp._tool_manager.get_tool("hermes_ask")
    assert tool is not None
    with pytest.raises(HermesError, match="hermes exited 2"):
        tool.fn(prompt="hi", session_id=None, toolsets=None)


def test_oauth_routes_present() -> None:
    """The streamable_http_app should mount /authorize, /token, and metadata."""
    cfg = _config()
    client = MagicMock()
    mcp = build_app(cfg, client)
    app = mcp.streamable_http_app()
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/authorize" in paths
    assert "/token" in paths
    assert "/.well-known/oauth-authorization-server" in paths


def test_allowed_hosts_propagated_to_transport_security() -> None:
    cfg = Config.from_env({**VALID_ENV, "MCP_ALLOWED_HOSTS": "hermes.example.com"})
    client = MagicMock()
    mcp = build_app(cfg, client)
    hosts = mcp.settings.transport_security.allowed_hosts  # type: ignore[union-attr]
    assert "hermes.example.com" in hosts
    assert "127.0.0.1:*" in hosts


def test_allowed_hosts_origins_handle_scheme_prefix() -> None:
    """An entry in MCP_ALLOWED_HOSTS that already has a scheme should not get
    'https://' prepended; an entry that doesn't should."""
    cfg = Config.from_env(
        {
            **VALID_ENV,
            "MCP_ALLOWED_HOSTS": "hermes.example.com,https://other.example.com",
        }
    )
    client = MagicMock()
    mcp = build_app(cfg, client)
    origins = mcp.settings.transport_security.allowed_origins  # type: ignore[union-attr]
    assert "https://hermes.example.com" in origins
    assert "https://other.example.com" in origins
    assert "https://https://other.example.com" not in origins


def test_oauth_issuer_url_no_double_slash_in_resource_url() -> None:
    """OAUTH_ISSUER_URL with a trailing slash must not produce '//mcp' in the
    derived resource_server_url."""
    cfg = Config.from_env({**VALID_ENV, "OAUTH_ISSUER_URL": "https://hermes.example.com/"})
    client = MagicMock()
    mcp = build_app(cfg, client)
    resource_url = str(mcp.settings.auth.resource_server_url)  # type: ignore[union-attr]
    assert "//mcp" not in resource_url.replace("https://", "")
    assert resource_url.endswith("/mcp")
