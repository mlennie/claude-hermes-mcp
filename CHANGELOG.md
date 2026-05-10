# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed (BREAKING)
- Auth replaced: OAuth 2.1 (authorization code + PKCE) instead of a single bearer token.
  Claude Desktop's Custom Connector UI requires this.
  - New required env vars: `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OAUTH_ISSUER_URL`.
  - Removed: `MCP_BEARER_TOKEN`.
- New `hermes-mcp mint-client` subcommand to generate a fresh client_id / client_secret.
- `MCP_ALLOWED_HOSTS` env var added so DNS-rebinding protection accepts the tunnel hostname.

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

[Unreleased]: https://github.com/mlennie/claude-hermes-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mlennie/claude-hermes-mcp/releases/tag/v0.1.0
