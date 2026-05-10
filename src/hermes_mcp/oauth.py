"""Single-user OAuth 2.1 authorization server provider.

The MCP transport spec (and Claude Desktop's Custom Connector UI) require an
OAuth 2.1 authorization server in front of the MCP endpoint. For a personal
bridge there is exactly one client and exactly one user, so this provider:

  - holds a single static (client_id, client_secret) pair, configured via env
  - auto-approves the /authorize step (security rests on the client_secret
    + PKCE binding at the /token exchange, not on a UI consent step)
  - mints opaque random access and refresh tokens, stored in memory
  - has no persistence: tokens evaporate on restart, the client just re-auths

Dynamic Client Registration is intentionally disabled. Anyone hitting
/register is told it is unsupported.

Concurrency: hermes-mcp is single-process and the dict mutations below are
guarded by Python's GIL on the basic operations we use (dict set/get/pop).
We do not need an explicit lock for single-user traffic.
"""

from __future__ import annotations

import hmac
import logging
import secrets
import time
from dataclasses import dataclass

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import (
    InvalidRedirectUriError,
    OAuthClientInformationFull,
    OAuthToken,
)
from pydantic import AnyUrl

logger = logging.getLogger(__name__)

DEFAULT_ACCESS_TOKEN_TTL = 3600  # 1 hour
DEFAULT_REFRESH_TOKEN_TTL = 30 * 24 * 3600  # 30 days
AUTHORIZATION_CODE_TTL = 60  # 1 minute (RFC 6749 §4.1.2 recommends short)


class _StaticClient(OAuthClientInformationFull):
    """Single static client. Accepts any redirect_uri sent by the client.

    Validating the redirect_uri against a pre-registered list is not useful
    here: we have one client whose `client_secret` is required at /token,
    and we have PKCE binding the code to the original code_challenge. An
    attacker who substitutes a redirect_uri cannot exchange the code without
    both secrets.
    """

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is None:
            raise InvalidRedirectUriError("redirect_uri is required")
        return redirect_uri


@dataclass
class StaticClientProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """In-memory OAuth provider for a single pre-shared client."""

    client_id: str
    client_secret: str
    access_token_ttl: int = DEFAULT_ACCESS_TOKEN_TTL
    refresh_token_ttl: int = DEFAULT_REFRESH_TOKEN_TTL

    def __post_init__(self) -> None:
        if not self.client_id or not self.client_secret:
            raise ValueError("client_id and client_secret are required")
        self._client = _StaticClient(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uris=[AnyUrl("http://localhost/")],  # placeholder; we override validation
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="client_secret_post",  # noqa: S106 — RFC 6749 method name, not a secret
        )
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._access_tokens: dict[str, AccessToken] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}
        self._refresh_to_access: dict[str, str] = {}

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        if hmac.compare_digest(client_id.encode(), self.client_id.encode()):
            return self._client
        return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        raise NotImplementedError(
            "Dynamic client registration is disabled. Configure OAUTH_CLIENT_ID "
            "and OAUTH_CLIENT_SECRET on the server and paste them into your client."
        )

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        # Auto-approve: mint a code and immediately redirect back to the client.
        code = secrets.token_urlsafe(32)
        self._auth_codes[code] = AuthorizationCode(
            code=code,
            scopes=params.scopes or [],
            expires_at=time.time() + AUTHORIZATION_CODE_TTL,
            client_id=str(client.client_id),
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        logger.info("oauth: issued authorization code (state=%s)", params.state)
        return construct_redirect_uri(
            str(params.redirect_uri),
            code=code,
            state=params.state,
        )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        return self._auth_codes.get(authorization_code)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        # Codes are single-use.
        self._auth_codes.pop(authorization_code.code, None)
        return self._mint_token_pair(client, authorization_code.scopes, authorization_code.resource)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        rt = self._refresh_tokens.get(refresh_token)
        if rt is None or rt.client_id != str(client.client_id):
            return None
        if rt.expires_at and rt.expires_at < int(time.time()):
            self._refresh_tokens.pop(refresh_token, None)
            return None
        return rt

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        # Rotate both: invalidate the old refresh + access pair before minting new.
        self._refresh_tokens.pop(refresh_token.token, None)
        old_access = self._refresh_to_access.pop(refresh_token.token, None)
        if old_access:
            self._access_tokens.pop(old_access, None)
        return self._mint_token_pair(client, scopes or refresh_token.scopes, None)

    async def load_access_token(self, token: str) -> AccessToken | None:
        at = self._access_tokens.get(token)
        if at is None:
            return None
        if at.expires_at and at.expires_at < int(time.time()):
            self._access_tokens.pop(token, None)
            return None
        return at

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        # Revocation endpoint is not exposed; FastMCP only calls this if
        # RevocationOptions().enabled. Provided for protocol completeness.
        if isinstance(token, AccessToken):
            self._access_tokens.pop(token.token, None)
        else:
            self._refresh_tokens.pop(token.token, None)
            old_access = self._refresh_to_access.pop(token.token, None)
            if old_access:
                self._access_tokens.pop(old_access, None)

    def _mint_token_pair(
        self,
        client: OAuthClientInformationFull,
        scopes: list[str],
        resource: str | None,
    ) -> OAuthToken:
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        now = int(time.time())
        self._access_tokens[access] = AccessToken(
            token=access,
            client_id=str(client.client_id),
            scopes=scopes,
            expires_at=now + self.access_token_ttl,
            resource=resource,
        )
        self._refresh_tokens[refresh] = RefreshToken(
            token=refresh,
            client_id=str(client.client_id),
            scopes=scopes,
            expires_at=now + self.refresh_token_ttl,
        )
        self._refresh_to_access[refresh] = access
        logger.info("oauth: minted token pair (expires_in=%ds)", self.access_token_ttl)
        return OAuthToken(
            access_token=access,
            token_type="Bearer",  # noqa: S106 — OAuth token-type literal, not a secret
            expires_in=self.access_token_ttl,
            refresh_token=refresh,
            scope=" ".join(scopes) if scopes else None,
        )


def mint_client_credentials() -> tuple[str, str]:
    """Generate a fresh client_id / client_secret pair for static registration."""
    return (
        f"hermes-mcp-{secrets.token_urlsafe(8)}",
        secrets.token_urlsafe(32),
    )
