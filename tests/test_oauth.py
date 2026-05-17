from __future__ import annotations

import asyncio
import time
from typing import cast

import pytest
from mcp.server.auth.provider import AuthorizationCode, AuthorizationParams
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull
from pydantic import AnyUrl

from hermes_mcp.oauth import StaticClientProvider, mint_client_credentials

CLIENT_ID = "hermes-mcp-test"
CLIENT_SECRET = "s" * 48


def _provider(**kwargs: int) -> StaticClientProvider:
    return StaticClientProvider(client_id=CLIENT_ID, client_secret=CLIENT_SECRET, **kwargs)


def _params(
    redirect_uri: str = "https://app.example.com/cb", state: str | None = "st-1"
) -> AuthorizationParams:
    return AuthorizationParams(
        state=state,
        scopes=[],
        code_challenge="dummy-challenge",
        redirect_uri=AnyUrl(redirect_uri),
        redirect_uri_provided_explicitly=True,
        resource=None,
    )


def test_mint_client_credentials_unique_and_strong() -> None:
    a_id, a_secret = mint_client_credentials()
    b_id, b_secret = mint_client_credentials()
    assert a_id != b_id
    assert a_secret != b_secret
    assert a_id.startswith("hermes-mcp-")
    # token_urlsafe(32) -> >= 40 char strings
    assert len(a_secret) >= 40


def test_constructor_rejects_empty_credentials() -> None:
    with pytest.raises(ValueError, match="required"):
        StaticClientProvider(client_id="", client_secret=CLIENT_SECRET)
    with pytest.raises(ValueError, match="required"):
        StaticClientProvider(client_id=CLIENT_ID, client_secret="")


def test_get_client_returns_static_client_as_public_pkce_only() -> None:
    """The registered client is a public client: `client_secret=None` and
    `token_endpoint_auth_method="none"`. This lets the SDK skip the
    client_secret check at /token (`mcp/server/auth/middleware/client_auth.py`
    branches on `client.client_secret` being truthy) while keeping PKCE
    mandatory. This is what unlocks Codex CLI / Cursor, whose MCP OAuth
    configs only carry `client_id`."""
    p = _provider()
    client = asyncio.run(p.get_client(CLIENT_ID))
    assert client is not None
    assert client.client_id == CLIENT_ID
    assert client.client_secret is None
    assert client.token_endpoint_auth_method == "none"


def test_get_client_unknown_returns_none() -> None:
    p = _provider()
    assert asyncio.run(p.get_client("not-the-client")) is None


def test_register_client_disabled() -> None:
    p = _provider()
    metadata = OAuthClientInformationFull(redirect_uris=[AnyUrl("https://x/cb")])
    with pytest.raises(NotImplementedError, match="Dynamic client registration"):
        asyncio.run(p.register_client(metadata))


def test_authorize_returns_redirect_with_code_and_state() -> None:
    p = _provider()
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    redirect = asyncio.run(p.authorize(client, _params()))
    assert redirect.startswith("https://app.example.com/cb")
    assert "code=" in redirect
    assert "state=st-1" in redirect


def test_validate_redirect_uri_allows_expected_schemes() -> None:
    p = _provider()
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    # Public-suffix HTTPS URLs.
    assert client.validate_redirect_uri(AnyUrl("https://app.example.com/cb")) is not None
    # Default custom schemes covering Claude Desktop / Claude.ai / Cursor.
    assert client.validate_redirect_uri(AnyUrl("claude://oauth/callback")) is not None
    assert client.validate_redirect_uri(AnyUrl("claudeai://oauth/callback")) is not None
    assert client.validate_redirect_uri(AnyUrl("cursor://anysphere.cursor-mcp/cb")) is not None
    # http only on localhost.
    assert client.validate_redirect_uri(AnyUrl("http://localhost:9999/x")) is not None
    assert client.validate_redirect_uri(AnyUrl("http://127.0.0.1:9999/x")) is not None


def test_validate_redirect_uri_rejects_scheme_not_in_default_allowlist() -> None:
    """A custom scheme not in the default set (e.g. `vscode://`) is rejected
    unless the operator adds it to OAUTH_ALLOWED_REDIRECT_SCHEMES."""
    p = _provider()
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    with pytest.raises(InvalidRedirectUriError, match="not allowed"):
        client.validate_redirect_uri(AnyUrl("vscode://continue.continue/oauth/callback"))


def test_validate_redirect_uri_accepts_custom_scheme_when_configured() -> None:
    """Operator adds `vscode` to OAUTH_ALLOWED_REDIRECT_SCHEMES → accepted."""
    p = StaticClientProvider(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        allowed_redirect_schemes=frozenset({"vscode"}),
    )
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    assert (
        client.validate_redirect_uri(AnyUrl("vscode://continue.continue/oauth/callback"))
        is not None
    )


def test_validate_redirect_uri_baseline_always_allowed_regardless_of_config() -> None:
    """`https` and `http`-on-localhost are baseline schemes; they're allowed
    even if the operator configures an allowlist that excludes them. This is
    the security floor for Codex CLI's HTTPS callbacks and for local testing."""
    p = StaticClientProvider(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        allowed_redirect_schemes=frozenset({"vscode"}),  # deliberately omits https/http
    )
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    assert client.validate_redirect_uri(AnyUrl("https://app.example.com/cb")) is not None
    assert client.validate_redirect_uri(AnyUrl("http://localhost:9999/cb")) is not None


def test_validate_redirect_uri_default_claude_schemes_rejected_under_custom_config() -> None:
    """If the operator explicitly configures schemes without `claude`/`claudeai`,
    those schemes are no longer accepted — the env var fully replaces the
    default custom-scheme list (baseline stays intact)."""
    p = StaticClientProvider(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        allowed_redirect_schemes=frozenset({"cursor"}),  # only cursor; no claude
    )
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    with pytest.raises(InvalidRedirectUriError, match="not allowed"):
        client.validate_redirect_uri(AnyUrl("claude://oauth/callback"))


def test_validate_redirect_uri_rejects_dangerous_schemes() -> None:
    """The /authorize redirect must not become an open redirector to javascript:
    or data: URIs even though PKCE protects token exchange."""
    p = _provider()
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    for evil in (
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "ftp://example.com/x",
    ):
        with pytest.raises(InvalidRedirectUriError, match="not allowed"):
            client.validate_redirect_uri(AnyUrl(evil))


def test_validate_redirect_uri_rejects_http_to_remote_host() -> None:
    """http:// is allowed only for localhost — preserves loopback testing
    without exposing the bridge to plaintext phishing redirects."""
    p = _provider()
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    with pytest.raises(InvalidRedirectUriError, match="only allowed for localhost"):
        client.validate_redirect_uri(AnyUrl("http://evil.example.com/cb"))


def test_validate_redirect_uri_rejects_none() -> None:
    p = _provider()
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    with pytest.raises(InvalidRedirectUriError):
        client.validate_redirect_uri(None)


def test_authorization_code_round_trip() -> None:
    p = _provider()
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    redirect = asyncio.run(p.authorize(client, _params()))
    code = redirect.split("code=")[1].split("&")[0]
    auth_code = asyncio.run(p.load_authorization_code(client, code))
    assert auth_code is not None
    assert auth_code.code == code
    assert auth_code.client_id == CLIENT_ID

    tokens = asyncio.run(p.exchange_authorization_code(client, auth_code))
    assert tokens.access_token
    assert tokens.refresh_token
    assert tokens.token_type == "Bearer"
    assert tokens.expires_in == 3600

    # Code is single-use after exchange.
    assert asyncio.run(p.load_authorization_code(client, code)) is None


def test_load_unknown_authorization_code() -> None:
    p = _provider()
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    assert asyncio.run(p.load_authorization_code(client, "no-such-code")) is None


def test_access_token_verifiable_via_load_access_token() -> None:
    p = _provider()
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    redirect = asyncio.run(p.authorize(client, _params()))
    code = redirect.split("code=")[1].split("&")[0]
    auth_code = cast(AuthorizationCode, asyncio.run(p.load_authorization_code(client, code)))
    tokens = asyncio.run(p.exchange_authorization_code(client, auth_code))

    loaded = asyncio.run(p.load_access_token(tokens.access_token))
    assert loaded is not None
    assert loaded.client_id == CLIENT_ID

    assert asyncio.run(p.load_access_token("not-a-real-token")) is None


def test_expired_access_token_rejected() -> None:
    p = _provider()
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    redirect = asyncio.run(p.authorize(client, _params()))
    code = redirect.split("code=")[1].split("&")[0]
    auth_code = cast(AuthorizationCode, asyncio.run(p.load_authorization_code(client, code)))
    tokens = asyncio.run(p.exchange_authorization_code(client, auth_code))

    # Backdate the stored expiry past now without sleeping (fast + deterministic).
    stored = p._access_tokens[tokens.access_token]
    p._access_tokens[tokens.access_token] = stored.model_copy(
        update={"expires_at": int(time.time()) - 1}
    )
    assert asyncio.run(p.load_access_token(tokens.access_token)) is None


def test_refresh_token_rotates_pair() -> None:
    p = _provider()
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    redirect = asyncio.run(p.authorize(client, _params()))
    code = redirect.split("code=")[1].split("&")[0]
    auth_code = cast(AuthorizationCode, asyncio.run(p.load_authorization_code(client, code)))
    tokens = asyncio.run(p.exchange_authorization_code(client, auth_code))

    rt = asyncio.run(p.load_refresh_token(client, tokens.refresh_token or ""))
    assert rt is not None

    new_tokens = asyncio.run(p.exchange_refresh_token(client, rt, []))
    assert new_tokens.access_token != tokens.access_token
    assert new_tokens.refresh_token != tokens.refresh_token

    # Old access and refresh tokens are invalidated.
    assert asyncio.run(p.load_access_token(tokens.access_token)) is None
    assert asyncio.run(p.load_refresh_token(client, tokens.refresh_token or "")) is None
    # New tokens work.
    assert asyncio.run(p.load_access_token(new_tokens.access_token)) is not None


def test_refresh_token_belonging_to_different_client_rejected() -> None:
    p = _provider()
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    redirect = asyncio.run(p.authorize(client, _params()))
    code = redirect.split("code=")[1].split("&")[0]
    auth_code = cast(AuthorizationCode, asyncio.run(p.load_authorization_code(client, code)))
    tokens = asyncio.run(p.exchange_authorization_code(client, auth_code))

    # Forge a different client and try to load the refresh token through it.
    other_client = OAuthClientInformationFull(
        client_id="someone-else",
        client_secret=CLIENT_SECRET,
        redirect_uris=[AnyUrl("https://x/cb")],
    )
    assert asyncio.run(p.load_refresh_token(other_client, tokens.refresh_token or "")) is None


def test_revoke_token_clears_storage() -> None:
    p = _provider()
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    redirect = asyncio.run(p.authorize(client, _params()))
    code = redirect.split("code=")[1].split("&")[0]
    auth_code = cast(AuthorizationCode, asyncio.run(p.load_authorization_code(client, code)))
    tokens = asyncio.run(p.exchange_authorization_code(client, auth_code))

    access = cast(object, asyncio.run(p.load_access_token(tokens.access_token)))
    assert access is not None
    asyncio.run(p.revoke_token(access))  # type: ignore[arg-type]
    assert asyncio.run(p.load_access_token(tokens.access_token)) is None


def test_authorization_code_reuse_rejected() -> None:
    """A second exchange of the same code must fail. The fix is atomic
    pop-then-mint, not the prior post-mint pop."""
    p = _provider()
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    redirect = asyncio.run(p.authorize(client, _params()))
    code = redirect.split("code=")[1].split("&")[0]
    auth_code = cast(AuthorizationCode, asyncio.run(p.load_authorization_code(client, code)))
    asyncio.run(p.exchange_authorization_code(client, auth_code))

    # Replay attempt — code is gone from storage.
    from mcp.server.auth.provider import TokenError as _TokenError

    with pytest.raises(_TokenError, match="already used"):
        asyncio.run(p.exchange_authorization_code(client, auth_code))


def test_refresh_token_reuse_rejected() -> None:
    """Concurrent /token requests with the same refresh token: only one wins."""
    p = _provider()
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    redirect = asyncio.run(p.authorize(client, _params()))
    code = redirect.split("code=")[1].split("&")[0]
    auth_code = cast(AuthorizationCode, asyncio.run(p.load_authorization_code(client, code)))
    tokens = asyncio.run(p.exchange_authorization_code(client, auth_code))
    rt = cast(object, asyncio.run(p.load_refresh_token(client, tokens.refresh_token or "")))
    assert rt is not None

    # First refresh succeeds, mints new pair.
    asyncio.run(p.exchange_refresh_token(client, rt, []))  # type: ignore[arg-type]

    # Second refresh with the same RT must fail (atomic pop already removed it).
    from mcp.server.auth.provider import TokenError as _TokenError

    with pytest.raises(_TokenError, match="already used"):
        asyncio.run(p.exchange_refresh_token(client, rt, []))  # type: ignore[arg-type]


def test_expired_refresh_token_rejected() -> None:
    p = _provider()
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    redirect = asyncio.run(p.authorize(client, _params()))
    code = redirect.split("code=")[1].split("&")[0]
    auth_code = cast(AuthorizationCode, asyncio.run(p.load_authorization_code(client, code)))
    tokens = asyncio.run(p.exchange_authorization_code(client, auth_code))

    # Backdate the refresh-token expiry past now without sleeping.
    rt_token = tokens.refresh_token or ""
    stored = p._refresh_tokens[rt_token]
    p._refresh_tokens[rt_token] = stored.model_copy(update={"expires_at": int(time.time()) - 1})

    assert asyncio.run(p.load_refresh_token(client, rt_token)) is None


def test_authorize_caps_outstanding_codes() -> None:
    """A drive-by attacker can't grow _auth_codes unboundedly."""
    from mcp.server.auth.provider import AuthorizeError

    from hermes_mcp.oauth import MAX_OUTSTANDING_AUTH_CODES

    p = _provider()
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    # Pre-fill to the cap with codes that won't reap (expires_at far in future).
    far_future = time.time() + 10_000
    for i in range(MAX_OUTSTANDING_AUTH_CODES):
        p._auth_codes[f"code-{i}"] = AuthorizationCode(
            code=f"code-{i}",
            scopes=[],
            expires_at=far_future,
            client_id=CLIENT_ID,
            code_challenge="x",
            redirect_uri=AnyUrl("https://app.example.com/cb"),
            redirect_uri_provided_explicitly=True,
            resource=None,
        )
    with pytest.raises(AuthorizeError, match="Too many"):
        asyncio.run(p.authorize(client, _params()))


def test_authorize_reaps_expired_codes_before_capping() -> None:
    p = _provider()
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    # Pre-fill with already-expired codes; the next authorize() should reap and accept.
    long_ago = time.time() - 120
    for i in range(100):
        p._auth_codes[f"old-{i}"] = AuthorizationCode(
            code=f"old-{i}",
            scopes=[],
            expires_at=long_ago,
            client_id=CLIENT_ID,
            code_challenge="x",
            redirect_uri=AnyUrl("https://app.example.com/cb"),
            redirect_uri_provided_explicitly=True,
            resource=None,
        )
    redirect = asyncio.run(p.authorize(client, _params()))
    assert "code=" in redirect
    # After authorize: the 100 expired entries are gone, only the new code remains.
    remaining_old = [c for c in p._auth_codes if c.startswith("old-")]
    assert remaining_old == []


def test_state_with_newline_is_sanitized_in_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Attacker-controlled `state` must not inject newlines into log lines."""
    p = _provider()
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    with caplog.at_level("INFO", logger="hermes_mcp.oauth"):
        asyncio.run(p.authorize(client, _params(state="evil\nFAKE LOG LINE: pwned")))
    msgs = [r.message for r in caplog.records if "issued authorization code" in r.message]
    assert msgs, "expected an issued-authorization-code log line"
    for m in msgs:
        # Newlines must be escaped before logging; the raw \n must not appear.
        assert "\n" not in m
        assert "FAKE LOG LINE" not in m or "\\n" in m


def test_ask_doc_is_not_lost_to_del() -> None:
    """Regression test: a prior version of hermes_client.ask put `del toolsets`
    above the docstring, which silently turned __doc__ into None."""
    from hermes_mcp.hermes_client import HermesClient as _HC

    assert _HC.ask.__doc__ is not None
    assert "session_id" in _HC.ask.__doc__
