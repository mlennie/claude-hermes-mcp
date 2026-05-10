"""CLI entrypoint tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from hermes_mcp.__main__ import main

VALID_ENV: dict[str, str] = {
    "OAUTH_CLIENT_ID": "hermes-mcp-test",
    "OAUTH_CLIENT_SECRET": "x" * 32,
    "OAUTH_ISSUER_URL": "https://hermes.example.com",
    "HERMES_API_KEY": "k" * 32,
}


def test_mint_client_prints_credentials(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["mint-client"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "OAUTH_CLIENT_ID=hermes-mcp-" in out
    assert "OAUTH_CLIENT_SECRET=" in out
    # Should also include the Claude Desktop paste-block hint.
    assert "custom connector" in out.lower()


def test_missing_required_env_returns_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Clear all OAuth env so config validation fails.
    for k in ("OAUTH_CLIENT_ID", "OAUTH_CLIENT_SECRET", "OAUTH_ISSUER_URL", "HERMES_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    rc = main(["doctor"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "config error" in err
    assert "OAUTH_CLIENT_ID" in err


def test_doctor_failure_returns_3(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for k, v in VALID_ENV.items():
        monkeypatch.setenv(k, v)
    # Make the gateway unreachable.
    monkeypatch.setenv("HERMES_API_URL", "http://127.0.0.1:1")
    rc = main(["doctor"])
    assert rc == 3
    err = capsys.readouterr().err
    assert "doctor:" in err


def test_doctor_success_prints_models(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for k, v in VALID_ENV.items():
        monkeypatch.setenv(k, v)
    import httpx

    def fake_get(url: str, **_kwargs: object) -> httpx.Response:
        if url.endswith("/v1/health"):
            return httpx.Response(200, text="ok")
        if url.endswith("/v1/models"):
            return httpx.Response(
                200,
                json={"object": "list", "data": [{"id": "hermes-agent"}]},
            )
        raise AssertionError(f"unexpected url {url}")

    with patch("hermes_mcp.doctor.httpx.get", fake_get):
        rc = main(["doctor"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "doctor: ok" in out
    assert "hermes-agent" in out
