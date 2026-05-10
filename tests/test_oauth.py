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


def test_get_client_returns_static_client() -> None:
    p = _provider()
    client = asyncio.run(p.get_client(CLIENT_ID))
    assert client is not None
    assert client.client_id == CLIENT_ID
    assert client.client_secret == CLIENT_SECRET


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


def test_validate_redirect_uri_permissive() -> None:
    p = _provider()
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    # Any URI works for the static client (security via PKCE + client_secret).
    assert client.validate_redirect_uri(AnyUrl("claude://oauth/callback")) is not None
    assert client.validate_redirect_uri(AnyUrl("http://localhost:9999/x")) is not None


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
    p = _provider(access_token_ttl=1)
    client = cast(OAuthClientInformationFull, asyncio.run(p.get_client(CLIENT_ID)))
    redirect = asyncio.run(p.authorize(client, _params()))
    code = redirect.split("code=")[1].split("&")[0]
    auth_code = cast(AuthorizationCode, asyncio.run(p.load_authorization_code(client, code)))
    tokens = asyncio.run(p.exchange_authorization_code(client, auth_code))

    # int(time.time()) granularity — sleep past the next integer second.
    time.sleep(2.1)
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
