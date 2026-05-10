from __future__ import annotations

import httpx
import pytest

from hermes_mcp.config import Config
from hermes_mcp.doctor import DoctorError, run_checks

_VALID = {
    "OAUTH_CLIENT_ID": "hermes-mcp-test",
    "OAUTH_CLIENT_SECRET": "x" * 32,
    "OAUTH_ISSUER_URL": "https://hermes.example.com",
    "HERMES_API_KEY": "k" * 32,
}


def _config(**overrides: str) -> Config:
    return Config.from_env({**_VALID, **overrides})


def _make_get(
    health_status: int = 200,
    models_status: int = 200,
    models_body: dict[str, object] | None = None,
):
    """Builds a fake httpx.get that returns 200/200 by default."""

    def fake_get(url: str, **_kwargs: object) -> httpx.Response:
        if url.endswith("/v1/health"):
            return httpx.Response(health_status, text="ok")
        if url.endswith("/v1/models"):
            body = (
                models_body
                if models_body is not None
                else {
                    "object": "list",
                    "data": [{"id": "hermes-agent", "object": "model"}],
                }
            )
            return httpx.Response(models_status, json=body)
        raise AssertionError(f"unexpected url {url}")

    return fake_get


def test_health_unreachable_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_kw: object) -> httpx.Response:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr("hermes_mcp.doctor.httpx.get", boom)
    with pytest.raises(DoctorError, match="hermes gateway unreachable"):
        run_checks(_config())


def test_health_non_200_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hermes_mcp.doctor.httpx.get", _make_get(health_status=503))
    with pytest.raises(DoctorError, match=r"returned 503 on /v1/health"):
        run_checks(_config())


def test_models_401_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hermes_mcp.doctor.httpx.get", _make_get(models_status=401))
    with pytest.raises(DoctorError, match="rejected the API key"):
        run_checks(_config())


def test_happy_path_returns_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hermes_mcp.doctor.httpx.get", _make_get())
    result = run_checks(_config())
    assert result.gateway_url == "http://127.0.0.1:8642"
    assert "hermes-agent" in result.gateway_models


def test_unknown_model_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        "hermes_mcp.doctor.httpx.get",
        _make_get(
            models_body={"object": "list", "data": [{"id": "different-model"}]},
        ),
    )
    with caplog.at_level("WARNING", logger="hermes_mcp.doctor"):
        run_checks(_config())
    assert any("not in /v1/models" in rec.message for rec in caplog.records)
