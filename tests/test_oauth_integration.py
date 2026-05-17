"""End-to-end OAuth + MCP integration tests against a TestClient-driven app.

Exercises the security-critical path that unit tests can't reach:
  - /mcp rejects unauthenticated requests
  - /mcp rejects forged bearer tokens
  - the full PKCE round-trip (authorize -> token -> /mcp) succeeds

Catches regressions in FastMCP / SDK wiring (e.g., if RequireAuthMiddleware
gets unwired or our auth_server_provider path stops registering).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from unittest.mock import MagicMock

from starlette.testclient import TestClient

from hermes_mcp.config import Config
from hermes_mcp.server import build_app

VALID_ENV: dict[str, str] = {
    "OAUTH_CLIENT_ID": "hermes-mcp-itest",
    "OAUTH_CLIENT_SECRET": "x" * 48,
    "OAUTH_ISSUER_URL": "http://localhost:8765",
    "HERMES_API_KEY": "k" * 32,
}


def _build_client() -> TestClient:
    cfg = Config.from_env(VALID_ENV)
    hermes = MagicMock()
    hermes.ask.return_value = "alive"
    mcp = build_app(cfg, hermes)
    return TestClient(mcp.streamable_http_app(), base_url="http://localhost:8765")


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    return verifier, challenge


def test_mcp_rejects_unauthenticated_request() -> None:
    with _build_client() as c:
        r = c.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0.0.1"},
                },
            },
        )
    assert r.status_code == 401, r.text


def test_mcp_rejects_forged_bearer() -> None:
    with _build_client() as c:
        r = c.post(
            "/mcp",
            headers={
                "Authorization": "Bearer not-a-real-access-token",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0.0.1"},
                },
            },
        )
    assert r.status_code == 401, r.text


def _authorize(c: TestClient, challenge: str) -> str:
    r = c.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": VALID_ENV["OAUTH_CLIENT_ID"],
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "redirect_uri": "https://example.com/cb",
            "state": "s",
        },
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    return r.headers["location"].split("code=")[1].split("&")[0]


def _initialize(c: TestClient, access_token: str) -> int:
    return c.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0.0.1"},
            },
        },
    ).status_code


def test_full_oauth_round_trip_then_mcp_initialize_claude_style() -> None:
    """Claude Desktop's flow: paste both client_id and client_secret in the
    connector UI, so its /token request includes a client_secret. The server
    accepts the request (PKCE is the real gate; the secret is ignored)."""
    verifier, challenge = _pkce_pair()
    with _build_client() as c:
        code = _authorize(c, challenge)
        r = c.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://example.com/cb",
                "client_id": VALID_ENV["OAUTH_CLIENT_ID"],
                "client_secret": VALID_ENV["OAUTH_CLIENT_SECRET"],
                "code_verifier": verifier,
            },
        )
        assert r.status_code == 200, r.text
        access_token = r.json()["access_token"]
        assert _initialize(c, access_token) == 200


def test_full_oauth_round_trip_codex_style_no_client_secret() -> None:
    """Codex CLI / Cursor flow: their MCP OAuth config has no client_secret
    field (verified empirically in codex-rs/config/src/mcp_types.rs:120-124),
    so their /token request omits client_secret entirely. PKCE alone must be
    sufficient for the exchange to succeed — this is the headline contract
    of the public-client change."""
    verifier, challenge = _pkce_pair()
    with _build_client() as c:
        code = _authorize(c, challenge)
        r = c.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://example.com/cb",
                "client_id": VALID_ENV["OAUTH_CLIENT_ID"],
                # NO client_secret
                "code_verifier": verifier,
            },
        )
        assert r.status_code == 200, r.text
        access_token = r.json()["access_token"]
        assert _initialize(c, access_token) == 200


def test_token_endpoint_ignores_wrong_client_secret_when_pkce_valid() -> None:
    """Since the bridge is a public client (token_endpoint_auth_method=none,
    client_secret=None on the registered client), the SDK no longer checks
    any client_secret value in the form — even an obviously-wrong one is
    accepted as long as PKCE is valid. Documents the new contract so a
    future refactor doesn't accidentally reintroduce secret enforcement."""
    verifier, challenge = _pkce_pair()
    with _build_client() as c:
        code = _authorize(c, challenge)
        r = c.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://example.com/cb",
                "client_id": VALID_ENV["OAUTH_CLIENT_ID"],
                "client_secret": "wrong-secret",
                "code_verifier": verifier,
            },
        )
        assert r.status_code == 200, r.text


def test_token_endpoint_rejects_wrong_pkce_verifier() -> None:
    _verifier, challenge = _pkce_pair()
    with _build_client() as c:
        r = c.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": VALID_ENV["OAUTH_CLIENT_ID"],
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "redirect_uri": "https://example.com/cb",
                "state": "s",
            },
            follow_redirects=False,
        )
        code = r.headers["location"].split("code=")[1].split("&")[0]

        r = c.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://example.com/cb",
                "client_id": VALID_ENV["OAUTH_CLIENT_ID"],
                "client_secret": VALID_ENV["OAUTH_CLIENT_SECRET"],
                "code_verifier": "wrong-verifier-doesnt-match-challenge",
            },
        )
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_grant"


def test_register_endpoint_not_mounted_when_dcr_disabled() -> None:
    """We pass ClientRegistrationOptions(enabled=False); /register must 404."""
    with _build_client() as c:
        r = c.post(
            "/register",
            json={
                "redirect_uris": ["https://attacker.example.com/cb"],
                "client_name": "rogue",
            },
        )
        assert r.status_code == 404
