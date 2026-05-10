# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-05-10

### Changed (BREAKING)
- **Auth replaced** with OAuth 2.1 (authorization code + PKCE) instead of a single bearer token.
  Claude Desktop's Custom Connector UI requires this.
  - New required env vars: `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OAUTH_ISSUER_URL`.
  - Removed: `MCP_BEARER_TOKEN`.
- **Backend swapped** from `hermes -z` subprocess to HTTP POST against the
  Hermes gateway's OpenAI-compatible API (`/v1/chat/completions`). Same brain
  Telegram talks to — sessions, skills, loaded tools all carry over.
  - New required env var: `HERMES_API_KEY` (the `API_SERVER_KEY` from `~/.hermes/.env`).
  - New optional env vars: `HERMES_API_URL` (default `http://127.0.0.1:8642`),
    `HERMES_MODEL` (default `hermes-agent`).
  - Removed: `HERMES_BIN`, `HERMES_TOOLSETS`, `HERMES_TIMEOUT_SECONDS`
    (replaced by `HERMES_REQUEST_TIMEOUT_SECONDS`).
  - `session_id` is now forwarded as the `X-Hermes-Session-Id` header.

### Added
- `hermes-mcp mint-client` subcommand to generate a fresh client_id / client_secret pair.
- `MCP_ALLOWED_HOSTS` env var so DNS-rebinding protection accepts the public tunnel hostname.
- `BIND_HOST` non-loopback values now emit a startup warning.
- `httpx` runtime dependency (`>=0.27,<1.0`).
- systemd hardening flags on `deploy/hermes-mcp.service`: `ProtectSystem=strict`,
  `ProtectHome=read-only` (with `ReadWritePaths=` for the env directory),
  `RestrictAddressFamilies`, `LockPersonality`, `MemoryDenyWriteExecute`,
  `CapabilityBoundingSet=`, `SystemCallFilter=@system-service`.

### Security
- **OAuth redirect-URI scheme allowlist** (`https`, `http` for localhost only,
  `claude`, `claudeai`). Prevents `/authorize` becoming an open redirector to
  `javascript:` / `data:` / `file:` URIs.
- **Atomic refresh-token rotation.** Concurrent `/token` requests with the
  same refresh token: only the first one wins; the second is rejected as
  `invalid_grant`. Approximates RFC 6819 reuse detection.
- **Atomic authorization-code single-use.** Pop-then-mint sequence ensures
  a code cannot be redeemed twice.
- **`/authorize` and access-token caps.** Drive-by attackers cannot grow
  in-memory state unboundedly; expired entries are reaped opportunistically.
- **Log injection mitigation.** OAuth `state` parameter is sanitized
  (newlines escaped, truncated to 64 chars) before logging.
- **Gateway error bodies redacted** from user-visible errors. A misbehaving
  gateway can no longer inject content into the bridge's `HermesError`
  responses to Claude. Bodies remain in DEBUG logs only.
- `httpx.post`/`httpx.get` calls use `follow_redirects=False`.

## [0.1.0] - TBD

### Added
- Initial release.
- `hermes_ask(prompt, session_id?, toolsets?)` MCP tool wrapping `hermes -z` and `hermes --continue`.
- Streamable HTTP transport via FastMCP + uvicorn.
- Bearer-token auth middleware (`hmac.compare_digest`).
- Startup doctor self-check (`hermes --version`).
- Env-var configuration with `.env.example`.
- systemd units for `hermes-mcp`, cloudflared, and ngrok in `deploy/`.
- README with architecture diagram, threat model, and tunnel setup walkthroughs.

[Unreleased]: https://github.com/mlennie/claude-hermes-mcp/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/mlennie/claude-hermes-mcp/releases/tag/v0.2.0
[0.1.0]: https://github.com/mlennie/claude-hermes-mcp/releases/tag/v0.1.0
