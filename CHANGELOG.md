# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **`hermes_reset()` tool.** Clears every job from the in-memory `JobStore`
  in one call, returning JSON like `{"cleared": 4, "by_status": {"running": 1, "pending": 3}}`.
  Same caveat as `hermes_cancel`: does NOT stop in-flight worker threads
  or gateway calls — workers whose jobs are wiped run to completion and
  no-op when their `mark_completed` / `mark_failed` finds an unknown id.
  The tool description warns the LLM that the job store is shared across
  all MCP callers (multiple Claude sessions, background Hermes-agent
  workflows), so reset is a global operation that should be confirmed
  with the user when other work might be in flight.
- `JobStore.reset_all() -> tuple[int, dict[JobStatus, int]]` helper backing
  the tool. Reaps expired terminal jobs before counting so the returned
  `by_status` reflects only jobs that were actually live in the store at
  call time. Typed against the existing `JobStatus` literal for stronger
  static checks.
- **Multi-client support.** Any MCP client that speaks Streamable HTTP +
  OAuth 2.1 can now connect — Claude Desktop / Claude.ai (existing),
  OpenAI Codex CLI, Cursor, and others. No more hardcoded Claude-only
  assumptions in the OAuth flow or tool descriptions.
- **`OAUTH_ALLOWED_REDIRECT_SCHEMES` env var.** Comma-separated list of
  OAuth redirect-URI custom schemes to accept (default:
  `claude,claudeai,cursor`). `https` and `http`-on-localhost are always
  allowed as a security baseline. Lets operators extend the allowlist
  for new clients (e.g. `vscode` for Continue) without code changes.

### Changed
- Tool descriptions for `hermes_ask` / `hermes_check` / `hermes_cancel` /
  `hermes_reset` are now client-neutral. No longer hardcode "Claude" as
  the consumer; async-mode timeout guidance now notes that enforcement
  varies by client (Claude.ai is ~2 min; Codex CLI, Cursor, others
  differ). All async/sync decision heuristics remain unchanged.
- README, CLAUDE.md, `.env.example`, and source-file docstrings reframed
  around generic MCP clients with explicit support for Claude Desktop,
  Codex CLI, and Cursor as the tested set.
- `hermes-mcp mint-client` output now points at any MCP client's config
  format, not just Claude Desktop's Custom Connector UI.

## [0.3.0] - 2026-05-16

### Added
- **Async job mode for `hermes_ask`.** New optional `async_mode: bool = False`
  parameter. When `True`, the call returns a JSON string
  `{"job_id":"<id>","status":"pending"}` immediately and runs the gateway
  request in a background thread. Designed to escape the MCP client's
  per-call timeout (~2 minutes for Claude.ai / Claude Desktop) when Hermes
  needs to chew on a long multi-step task.
- **`hermes_check(job_id)` tool.** Returns JSON with `status` ∈
  `{pending, running, completed, failed, cancelled, unknown}`, plus
  `created_at` / `finished_at` epoch timestamps, `prompt_chars`, optional
  `session_id`, and `result` or `error`.
- **`hermes_cancel(job_id)` tool.** Releases the bookkeeping for an
  in-flight async job. **Does NOT stop the gateway work** — Python cannot
  safely kill a thread mid-I/O, so the worker runs to completion and any
  side effects happen anyway. Use this when you want to release the
  *result*, not undo the *work*. Tool description spells this out.
- In-memory `JobStore` (`src/hermes_mcp/jobs.py`) with ~24h TTL, 1000-job
  cap, lazy cleanup on access. Like OAuth state, jobs are not persisted —
  a server restart loses every in-flight or completed job.
- Tool description for `hermes_ask` documents `async_mode` and tells the
  caller about `hermes_check` and `hermes_cancel`.

### Changed
- **Single-tool design rescinded** (see CLAUDE.md). The server now exposes
  three tools tightly coupled around the async-job lifecycle: `hermes_ask`
  (submit), `hermes_check` (poll), `hermes_cancel` (release). The shape of
  `hermes_ask` in sync mode is unchanged — old callers continue to work
  without changes.
- `JobStore.mark_completed` and `JobStore.mark_failed` are now
  terminal-state-aware: a late-finishing worker thread cannot overwrite a
  cancellation (or any other terminal state). Both methods now return
  `bool` to signal whether the state actually changed.

### Security
- Unexpected worker-thread exceptions surface only their type name in the
  job record's `error` field (not `str(exc)`). Matches the existing
  invariant that gateway error bodies are not echoed in user-visible
  errors; the full traceback still lands in the server log at ERROR.
- Cancelled jobs never accept a late `result` payload from the worker
  thread — prevents a "phantom result" race where the user thinks they
  cancelled and then sees a result appear anyway.

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

[Unreleased]: https://github.com/mlennie/claude-hermes-mcp/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/mlennie/claude-hermes-mcp/releases/tag/v0.3.0
[0.2.0]: https://github.com/mlennie/claude-hermes-mcp/releases/tag/v0.2.0
[0.1.0]: https://github.com/mlennie/claude-hermes-mcp/releases/tag/v0.1.0
