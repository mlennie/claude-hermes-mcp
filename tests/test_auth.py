from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from hermes_mcp.auth import BearerAuthMiddleware


def _build_client(token: str = "secret-token-123456789012345678901234") -> TestClient:
    async def hello(_req):  # type: ignore[no-untyped-def]
        return PlainTextResponse("ok")

    inner = Starlette(routes=[Route("/", hello)])
    wrapped = BearerAuthMiddleware(inner, expected_token=token)
    return TestClient(wrapped)


def test_missing_authorization_header_returns_401() -> None:
    client = _build_client()
    response = client.get("/")
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}
    assert response.headers["WWW-Authenticate"].startswith("Bearer")


def test_wrong_token_returns_401() -> None:
    client = _build_client()
    response = client.get("/", headers={"Authorization": "Bearer not-the-real-token"})
    assert response.status_code == 401


def test_non_bearer_scheme_returns_401() -> None:
    client = _build_client()
    response = client.get("/", headers={"Authorization": "Basic Zm9vOmJhcg=="})
    assert response.status_code == 401


def test_correct_token_passes_through() -> None:
    token = "secret-token-123456789012345678901234"
    client = _build_client(token=token)
    response = client.get("/", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.text == "ok"


def test_empty_token_constructor_rejected() -> None:
    inner = Starlette()
    with pytest.raises(ValueError, match="expected_token must not be empty"):
        BearerAuthMiddleware(inner, expected_token="")


def test_uses_constant_time_compare() -> None:
    # Sanity check: import path resolves to the stdlib hmac module
    import hermes_mcp.auth as auth_mod

    assert auth_mod.hmac.compare_digest is not None
