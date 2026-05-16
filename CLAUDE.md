# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
uv venv .venv --python 3.11 && source .venv/bin/activate && uv pip install -e ".[dev]"

# Full CI suite (must all pass)
ruff check . && ruff format --check . && mypy src/ && pytest

# Individual checks
ruff check .                # lint
ruff format .               # auto-format
mypy src/                   # type-check (strict mode, src/ only — mcp module excluded)
pytest                      # all tests
pytest tests/test_oauth.py  # single test file
pytest -k "test_name"       # single test by name

# Run / inspect the server
hermes-mcp serve            # or: python -m hermes_mcp serve
hermes-mcp doctor           # startup self-check (probes the gateway)
hermes-mcp mint-client      # generate a fresh OAuth client_id / client_secret
```

## Architecture

**hermes-mcp** is an MCP bridge that lets Claude Desktop / Claude.ai delegate tasks to a locally running **Hermes Agent**. Claude calls one MCP tool (`hermes_ask`) over an HTTPS tunnel; the bridge gates that with OAuth 2.1 and forwards each call to the Hermes gateway's OpenAI-compatible HTTP API.

```
Claude.ai
  │  HTTPS via cloudflared tunnel
  ▼
hermes-mcp (this project, listening on 127.0.0.1:8765)
  ├─ OAuth 2.1 (authorization code + PKCE), single static client_id/secret
  └─ HTTP POST to the gateway
     │
     ▼
hermes-gateway (127.0.0.1:8642, OpenAI-compatible /v1/chat/completions)
  └─ same AIAgent loop that drives Telegram (skills, tools, sessions)
```

The gateway is a **separate, long-running process** owned by the user (typically a `systemd --user` service). hermes-mcp does not spawn it; it just sends HTTP requests.

The six source modules in `src/hermes_mcp/` have clean single responsibilities:

- **`config.py`** — frozen `Config` dataclass parsed from env vars. Required: `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OAUTH_ISSUER_URL`, `HERMES_API_KEY`. Validates the issuer URL is HTTPS (or `http://localhost`), the client_secret is ≥32 chars, and warns if `BIND_HOST` is non-loopback.
- **`oauth.py`** — `StaticClientProvider` implements the MCP SDK's `OAuthAuthorizationServerProvider` protocol with one pre-shared client. Mints opaque 256-bit access tokens (1h TTL) and refresh tokens (30d, rotated atomically on use). PKCE-S256 enforced by the SDK. DCR is disabled. `_StaticClient.validate_redirect_uri` enforces a scheme allowlist (`https`, `http`-on-localhost, `claude`, `claudeai`) so `/authorize` cannot become an open redirector to `javascript:` / `data:` URIs.
- **`hermes_client.py`** — `HermesClient.ask()` does `httpx.post` to the gateway's `/v1/chat/completions` with `Authorization: Bearer $HERMES_API_KEY`. `session_id` is forwarded as `X-Hermes-Session-Id`. `toolsets` is accepted for backward-compat but ignored — toolset selection now lives in the Hermes config (`platform_toolsets.api_server`). Gateway error bodies are NOT echoed in user-visible errors (DEBUG only).
- **`jobs.py`** — `JobStore` is a thread-safe in-memory dict of `Job` records, used by `hermes_ask(..., async_mode=True)`, `hermes_check`, and `hermes_cancel`. Lazy TTL reap (24h) on every access, 1000-job cap. In-memory only by design; restart drops everything. `mark_completed`/`mark_failed` are terminal-state-aware so a late-finishing worker cannot overwrite a cancellation. Times use `time.time()` (wall clock, epoch seconds) so they round-trip cleanly through JSON to the caller; small risk of confusion if the system clock jumps backwards, accepted in exchange for code simplicity.
- **`server.py`** — `build_app()` constructs a `FastMCP` instance with `auth_server_provider`, `AuthSettings`, and `transport_security`. Registers three tools: `hermes_ask` (sync default; `async_mode=True` spawns a daemon thread and returns a `job_id`), `hermes_check(job_id)`, and `hermes_cancel(job_id)`. FastMCP itself adds `/authorize`, `/token`, `/.well-known/oauth-authorization-server`, and the `RequireAuthMiddleware` that gates `/mcp`. `serve()` runs uvicorn.
- **`doctor.py`** — `run_checks()` probes the gateway's `/v1/health` (no auth) and `/v1/models` (with `HERMES_API_KEY`); warns if `HERMES_MODEL` isn't in the returned model list.

**Three-tool design.** The tools form a tight lifecycle: submit (`hermes_ask`), poll (`hermes_check`), abandon (`hermes_cancel`). Do not add tools for *new* use cases (different actions, different domains) without discussing in an issue first.

**Cancellation is a tombstone, not a kill switch.** `hermes_cancel` updates this server's bookkeeping; the worker thread keeps running and the gateway keeps doing whatever it was doing. There is no way around this in CPython — you cannot safely kill a thread blocked on `httpx.post`. The tool's description spells this out loudly so the LLM relays the caveat to the user. If we ever want real cancellation, the path is to rewrite `HermesClient` against `httpx.AsyncClient` with cancellation tokens and run the whole server on asyncio — large refactor, scoped for a future major version.

## Key constraints

- All four required env vars must be set or the server refuses to start.
- `client_secret` comparison uses `hmac.compare_digest()` (delegated to the MCP SDK's `ClientAuthenticator`).
- Access tokens are in-memory only — by design. Restart invalidates all sessions. **Claude Desktop does NOT re-auth transparently** in practice: it surfaces "Error occurred during tool execution" on the next call and the user has to manually Disconnect / Reconnect the connector once. The `client_id` / `client_secret` are saved on the connector, so the reconnect doesn't require re-pasting credentials. (Persisting tokens — and async-mode jobs — to disk is on the v0.4.0 roadmap.)
- Async-mode jobs are also in-memory only (`jobs.py`). A server restart drops every job, in-flight or completed; if a user is mid-poll they will see `status: unknown`. The same Disconnect/Reconnect dance applies after a restart.
- Refresh-token rotation is **atomic-pop-then-mint** in `oauth.py` — concurrent `/token` requests with the same refresh token cannot both succeed.
- Prompt content must only be logged at DEBUG level, not INFO (privacy by default). The `state` query parameter is sanitized before logging. Async-job records intentionally store only `prompt_chars` (not the prompt itself).
- Unexpected (non-`HermesError`) exceptions in the async worker thread surface as `error: "unexpected error: <ExceptionType>"` — never `str(exc)` — to preserve the existing invariant that gateway and library error bodies are not echoed in user-facing errors. Full traceback lands in the server log at ERROR.
- `BIND_HOST` defaults to `127.0.0.1`; binding elsewhere gets a startup warning.
- mypy is run on `src/` only — the `mcp` package lacks stubs and is excluded.
- Python ≥ 3.11 required; CI tests 3.11 and 3.12.
- Test count is 112 as of v0.3.0; a sudden drop is a regression smell.

## Deployment shape

This project ships with `deploy/hermes-mcp.service` and `deploy/cloudflared.service` as **systemd user units** (matching the `hermes-gateway` / `mcp-proxy` services it sits next to). Env file lives at `~/.config/hermes-mcp/env` mode 0600. `loginctl enable-linger` is required so user services start at boot.

`deploy/hermes-mcp.service` ships with non-trivial hardening flags: `ProtectSystem=strict`, `ProtectHome=read-only` + `ReadWritePaths=%h/.config/hermes-mcp`, `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`, `LockPersonality=true`, `MemoryDenyWriteExecute=true`, empty `CapabilityBoundingSet=`, and `SystemCallFilter=@system-service` (excluding `@privileged @resources`). They are verified to start cleanly with the current Python deps; **do not strip them without intent** and re-test the service start. If a future dependency needs JIT or syscalls outside `@system-service`, narrow the rule rather than removing it.

## Release process

Bump version in `src/hermes_mcp/__init__.py` and `pyproject.toml`, move `Unreleased` section in `CHANGELOG.md` to the new version with today's date, tag `v0.X.Y`, push. GitHub Actions publishes to PyPI via trusted publishing.
