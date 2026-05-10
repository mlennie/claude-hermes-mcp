from __future__ import annotations

import pytest

from hermes_mcp.config import Config, ConfigError

VALID_BASE: dict[str, str] = {
    "OAUTH_CLIENT_ID": "hermes-mcp-test",
    "OAUTH_CLIENT_SECRET": "x" * 32,
    "OAUTH_ISSUER_URL": "https://hermes.example.com",
    "HERMES_API_KEY": "k" * 32,
}


def test_requires_oauth_client_id() -> None:
    env = {**VALID_BASE}
    env.pop("OAUTH_CLIENT_ID")
    with pytest.raises(ConfigError, match="OAUTH_CLIENT_ID is required"):
        Config.from_env(env)


def test_requires_oauth_client_secret() -> None:
    env = {**VALID_BASE}
    env.pop("OAUTH_CLIENT_SECRET")
    with pytest.raises(ConfigError, match="OAUTH_CLIENT_SECRET is required"):
        Config.from_env(env)


def test_short_client_secret_rejected() -> None:
    env = {**VALID_BASE, "OAUTH_CLIENT_SECRET": "short"}
    with pytest.raises(ConfigError, match="at least 32 characters"):
        Config.from_env(env)


def test_requires_issuer_url() -> None:
    env = {**VALID_BASE}
    env.pop("OAUTH_ISSUER_URL")
    with pytest.raises(ConfigError, match="OAUTH_ISSUER_URL is required"):
        Config.from_env(env)


def test_requires_hermes_api_key() -> None:
    env = {**VALID_BASE}
    env.pop("HERMES_API_KEY")
    with pytest.raises(ConfigError, match="HERMES_API_KEY is required"):
        Config.from_env(env)


def test_issuer_url_must_be_https_or_localhost() -> None:
    env = {**VALID_BASE, "OAUTH_ISSUER_URL": "http://example.com"}
    with pytest.raises(ConfigError, match="must be HTTPS"):
        Config.from_env(env)


def test_localhost_http_issuer_allowed() -> None:
    cfg = Config.from_env({**VALID_BASE, "OAUTH_ISSUER_URL": "http://localhost:8765"})
    assert cfg.oauth_issuer_url == "http://localhost:8765"


def test_issuer_url_trailing_slash_stripped() -> None:
    cfg = Config.from_env({**VALID_BASE, "OAUTH_ISSUER_URL": "https://hermes.example.com/"})
    assert cfg.oauth_issuer_url == "https://hermes.example.com"


def test_minimal_valid_config() -> None:
    cfg = Config.from_env(VALID_BASE)
    assert cfg.oauth_client_id == "hermes-mcp-test"
    assert cfg.oauth_client_secret == "x" * 32
    assert cfg.oauth_issuer_url == "https://hermes.example.com"
    assert cfg.hermes_api_url == "http://127.0.0.1:8642"
    assert cfg.hermes_api_key == "k" * 32
    assert cfg.hermes_model == "hermes-agent"
    assert cfg.hermes_request_timeout_seconds == 300
    assert cfg.bind_host == "127.0.0.1"
    assert cfg.bind_port == 8765
    assert cfg.allowed_hosts == ()
    assert cfg.log_level == "INFO"


def test_hermes_api_url_validated() -> None:
    with pytest.raises(ConfigError, match="must be http:// or https://"):
        Config.from_env({**VALID_BASE, "HERMES_API_URL": "ftp://nope"})


def test_hermes_api_url_trailing_slash_stripped() -> None:
    cfg = Config.from_env({**VALID_BASE, "HERMES_API_URL": "http://127.0.0.1:8642/"})
    assert cfg.hermes_api_url == "http://127.0.0.1:8642"


def test_hermes_model_override() -> None:
    cfg = Config.from_env({**VALID_BASE, "HERMES_MODEL": "hermes"})
    assert cfg.hermes_model == "hermes"


def test_port_range_validated() -> None:
    with pytest.raises(ConfigError, match=r"BIND_PORT must be in 1\.\.65535"):
        Config.from_env({**VALID_BASE, "BIND_PORT": "0"})
    with pytest.raises(ConfigError, match=r"BIND_PORT must be in 1\.\.65535"):
        Config.from_env({**VALID_BASE, "BIND_PORT": "70000"})


def test_port_must_be_integer() -> None:
    with pytest.raises(ConfigError, match="BIND_PORT must be an integer"):
        Config.from_env({**VALID_BASE, "BIND_PORT": "abc"})


def test_request_timeout_validated() -> None:
    with pytest.raises(ConfigError, match="HERMES_REQUEST_TIMEOUT_SECONDS must be positive"):
        Config.from_env({**VALID_BASE, "HERMES_REQUEST_TIMEOUT_SECONDS": "0"})


def test_allowed_hosts_parsed() -> None:
    cfg = Config.from_env(
        {**VALID_BASE, "MCP_ALLOWED_HOSTS": "hermes.example.com,foo.trycloudflare.com"}
    )
    assert cfg.allowed_hosts == ("hermes.example.com", "foo.trycloudflare.com")


def test_log_level_validated() -> None:
    with pytest.raises(ConfigError, match="LOG_LEVEL must be one of"):
        Config.from_env({**VALID_BASE, "LOG_LEVEL": "VERBOSE"})


def test_log_level_normalized_to_upper() -> None:
    cfg = Config.from_env({**VALID_BASE, "LOG_LEVEL": "debug"})
    assert cfg.log_level == "DEBUG"
