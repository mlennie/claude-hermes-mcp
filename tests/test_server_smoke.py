"""Smoke test: build the FastMCP server, confirm hermes_ask is registered,
and confirm the tool works when the underlying HermesClient is mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from hermes_mcp.config import Config
from hermes_mcp.server import build_app


def _config() -> Config:
    return Config.from_env({"MCP_BEARER_TOKEN": "x" * 32})


def test_build_app_registers_hermes_ask() -> None:
    cfg = _config()
    client = MagicMock()
    mcp, _wrapped = build_app(cfg, client)
    tool_names = {t.name for t in mcp._tool_manager.list_tools()}
    assert "hermes_ask" in tool_names


def test_hermes_ask_invokes_client() -> None:
    cfg = _config()
    client = MagicMock()
    client.ask.return_value = "the answer"
    mcp, _ = build_app(cfg, client)
    tool = mcp._tool_manager.get_tool("hermes_ask")
    assert tool is not None
    fn = tool.fn
    result = fn(prompt="hi", session_id=None, toolsets=None)
    assert result == "the answer"
    client.ask.assert_called_once_with("hi", session_id=None, toolsets=None)
