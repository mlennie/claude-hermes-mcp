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
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
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

# Caps to prevent unbounded growth from drive-by /authorize calls.
MAX_OUTSTANDING_AUTH_CODES = 1024
MAX_OUTSTANDING_ACCESS_TOKENS = 4096

# Redirect-URI schemes the bridge will accept. PKCE + client_secret protect
# the token exchange, but `/authorize` redirects out to whatever URI the
# request specifies — we should not let that be a `javascript:`, `file:`,
# or `data:` URL or anything else that would turn this endpoint into an
# open redirector to dangerous schemes.
_ALLOWED_REDIRECT_SCHEMES = frozenset(
    {
        "https",
        "http",  # only honored for localhost; see _check_redirect_uri
        "claude",
        "claudeai",
    }
)


def _check_redirect_uri(redirect_uri: AnyUrl) -> None:
    """Reject schemes/hosts that would turn the OAuth flow into an open
    redirector to dangerous targets. Permissive within sane bounds — we
    do not pin specific Claude callback URIs because they are subject to
    change without notice."""
    scheme = (redirect_uri.scheme or "").lower()
    if scheme not in _ALLOWED_REDIRECT_SCHEMES:
        raise InvalidRedirectUriError(f"redirect_uri scheme {scheme!r} is not allowed")
    if scheme == "http" and redirect_uri.host not in ("localhost", "127.0.0.1", "::1"):
        raise InvalidRedirectUriError("redirect_uri scheme 'http' is only allowed for localhost")


def _safe_state(state: str | None) -> str:
    """Sanitize the OAuth `state` value before logging. The client controls
    state — without sanitization, an attacker hitting `/authorize` could
    inject log lines via newlines.
    """
    if not state:
        return "(none)"
    return state.replace("\n", "\\n").replace("\r", "\\r")[:64]


class _StaticClient(OAuthClientInformationFull):
    """Single static client. Accepts any redirect_uri sent by the client,
    subject to a scheme allowlist enforced by `_check_redirect_uri`.

    Validating the redirect_uri against a *pre-registered list* is not
    useful here: we have one client whose `client_secret` is required at
    /token, and we have PKCE binding the code to the original
    code_challenge. An attacker who substitutes a redirect_uri cannot
    exchange the code without both secrets.

    Validating the redirect_uri's *scheme* is, however, useful: without it
    `/authorize` would happily redirect to `javascript:` or `data:` URIs
    on request, turning the endpoint into an open redirector.
    """

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is None:
            raise InvalidRedirectUriError("redirect_uri is required")
        _check_redirect_uri(redirect_uri)
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
        # Reap expired codes opportunistically so `/authorize` is the only
        # write path that grows the dict.
        self._reap_expired_codes()
        if len(self._auth_codes) >= MAX_OUTSTANDING_AUTH_CODES:
            logger.warning(
                "oauth: refusing /authorize — outstanding-code cap reached (%d)",
                MAX_OUTSTANDING_AUTH_CODES,
            )
            raise AuthorizeError("server_error", "Too many outstanding authorization codes")

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
        logger.info("oauth: issued authorization code (state=%s)", _safe_state(params.state))
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
        # Codes are single-use: pop *atomically* before minting so concurrent
        # exchanges of the same code can't both succeed.
        if self._auth_codes.pop(authorization_code.code, None) is None:
            raise TokenError("invalid_grant", "authorization code was already used")
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
        # Atomic pop *before* minting so concurrent /token exchanges of the
        # same refresh token can't both produce valid pairs. RFC 6819 §5.2.2.3
        # recommends rotation; this also approximates reuse detection
        # (second arrival sees the token gone and is rejected as invalid_grant).
        if self._refresh_tokens.pop(refresh_token.token, None) is None:
            raise TokenError("invalid_grant", "refresh token was already used")
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

    def _reap_expired_codes(self) -> None:
        now = time.time()
        expired = [c for c, ac in self._auth_codes.items() if ac.expires_at < now]
        for c in expired:
            self._auth_codes.pop(c, None)

    def _mint_token_pair(
        self,
        client: OAuthClientInformationFull,
        scopes: list[str],
        resource: str | None,
    ) -> OAuthToken:
        # Cap outstanding tokens. Under normal operation every token here is
        # live (Claude refreshes well before expiry); hitting this means
        # something is wrong (a runaway client) and refusing is the right call.
        if len(self._access_tokens) >= MAX_OUTSTANDING_ACCESS_TOKENS:
            self._reap_expired_access_tokens()
            if len(self._access_tokens) >= MAX_OUTSTANDING_ACCESS_TOKENS:
                # No perfect TokenErrorCode for "we're out of capacity"; the
                # closest is invalid_request — RFC 6749 doesn't model rate-limit
                # in the token-error set.
                raise TokenError("invalid_request", "Too many outstanding access tokens")

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

    def _reap_expired_access_tokens(self) -> None:
        now = int(time.time())
        expired = [
            t for t, at in self._access_tokens.items() if at.expires_at and at.expires_at < now
        ]
        for t in expired:
            self._access_tokens.pop(t, None)


def mint_client_credentials() -> tuple[str, str]:
    """Generate a fresh client_id / client_secret pair for static registration."""
    return (
        f"hermes-mcp-{secrets.token_urlsafe(8)}",
        secrets.token_urlsafe(32),
    )
