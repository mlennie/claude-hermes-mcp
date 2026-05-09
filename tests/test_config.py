from __future__ import annotations

import pytest

from hermes_mcp.config import Config, ConfigError


def test_requires_bearer_token() -> None:
    with pytest.raises(ConfigError, match="MCP_BEARER_TOKEN is required"):
        Config.from_env({})


def test_blank_token_rejected() -> None:
    with pytest.raises(ConfigError, match="MCP_BEARER_TOKEN is required"):
        Config.from_env({"MCP_BEARER_TOKEN": "   "})


def test_minimal_valid_config() -> None:
    cfg = Config.from_env({"MCP_BEARER_TOKEN": "x" * 32})
    assert cfg.bearer_token == "x" * 32
    assert cfg.hermes_bin == "hermes"
    assert cfg.bind_host == "127.0.0.1"
    assert cfg.bind_port == 8765
    assert cfg.hermes_timeout_seconds == 300
    assert cfg.hermes_toolsets == ()
    assert cfg.log_level == "INFO"


def test_port_range_validated() -> None:
    with pytest.raises(ConfigError, match=r"BIND_PORT must be in 1\.\.65535"):
        Config.from_env({"MCP_BEARER_TOKEN": "tok", "BIND_PORT": "0"})
    with pytest.raises(ConfigError, match=r"BIND_PORT must be in 1\.\.65535"):
        Config.from_env({"MCP_BEARER_TOKEN": "tok", "BIND_PORT": "70000"})


def test_port_must_be_integer() -> None:
    with pytest.raises(ConfigError, match="BIND_PORT must be an integer"):
        Config.from_env({"MCP_BEARER_TOKEN": "tok", "BIND_PORT": "abc"})


def test_timeout_validated() -> None:
    with pytest.raises(ConfigError, match="HERMES_TIMEOUT_SECONDS must be positive"):
        Config.from_env({"MCP_BEARER_TOKEN": "tok", "HERMES_TIMEOUT_SECONDS": "0"})


def test_toolsets_parsed() -> None:
    cfg = Config.from_env(
        {"MCP_BEARER_TOKEN": "tok", "HERMES_TOOLSETS": "web, filesystem ,, email "}
    )
    assert cfg.hermes_toolsets == ("web", "filesystem", "email")


def test_log_level_validated() -> None:
    with pytest.raises(ConfigError, match="LOG_LEVEL must be one of"):
        Config.from_env({"MCP_BEARER_TOKEN": "tok", "LOG_LEVEL": "VERBOSE"})


def test_log_level_normalized_to_upper() -> None:
    cfg = Config.from_env({"MCP_BEARER_TOKEN": "tok", "LOG_LEVEL": "debug"})
    assert cfg.log_level == "DEBUG"
