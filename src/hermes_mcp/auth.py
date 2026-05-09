"""Bearer-token authentication middleware.

Wraps the FastMCP Starlette app. Constant-time comparison; never logs token
values. Returns 401 with a generic body on missing or invalid credentials.
"""

from __future__ import annotations

import hmac
import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

_AUTH_HEADER = b"authorization"
_BEARER_PREFIX = "Bearer "


class BearerAuthMiddleware:
    """ASGI middleware that requires `Authorization: Bearer <token>`."""

    def __init__(self, app: ASGIApp, expected_token: str) -> None:
        if not expected_token:
            raise ValueError("expected_token must not be empty")
        self._app = app
        self._expected = expected_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        if not self._authorized(scope):
            response = JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="hermes-mcp"'},
            )
            await response(scope, receive, send)
            return

        await self._app(scope, receive, send)

    def _authorized(self, scope: Scope) -> bool:
        for name, value in scope.get("headers", []):
            if name.lower() == _AUTH_HEADER:
                try:
                    decoded = value.decode("latin-1")
                except UnicodeDecodeError:
                    return False
                if not decoded.startswith(_BEARER_PREFIX):
                    return False
                token = decoded[len(_BEARER_PREFIX) :].strip()
                return hmac.compare_digest(token, self._expected)
        return False
