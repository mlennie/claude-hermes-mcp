# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
uv venv .venv --python 3.11 && source .venv/bin/activate && uv pip install -e ".[dev]"

# Full CI suite (must all pass)
ruff check . && ruff format --check . && mypy src/ && pytest

# Individual checks
ruff check .            # lint
ruff format .           # auto-format
mypy src/               # type-check (strict mode, src/ only — mcp module excluded)
pytest                  # all tests
pytest tests/test_auth.py   # single test file
pytest -k "test_name"       # single test by name

# Run the server
hermes-mcp serve        # or: python -m hermes_mcp serve
hermes-mcp doctor       # startup self-check
```

## Architecture

**hermes-mcp** is an MCP server that bridges Claude Desktop/Mobile to a local Hermes Agent (CLI tool) via a secure HTTPS tunnel. Claude calls one MCP tool (`hermes_ask`), which delegates to the `hermes` binary via subprocess.

```
Claude → HTTPS tunnel → hermes-mcp → subprocess → hermes CLI
```

The five source modules in `src/hermes_mcp/` have clean single responsibilities:

- **`config.py`** — frozen `Config` dataclass parsed from env vars; validates bearer token (required), port, timeout, log level
- **`auth.py`** — `BearerAuthMiddleware` ASGI middleware; uses `hmac.compare_digest()` for constant-time comparison; returns 401 on any auth failure
- **`hermes_client.py`** — `HermesClient` wraps the `hermes` CLI via `subprocess.run()` (never `shell=True`); raises `HermesError` on timeout/nonzero exit; never logs prompt body at INFO level
- **`server.py`** — `build_app()` creates a FastMCP server with the single `hermes_ask` tool, wraps it in `BearerAuthMiddleware`, and exposes it via Starlette; `serve()` runs uvicorn
- **`doctor.py`** — `run_checks()` locates and validates the hermes binary before startup; warns if bearer token < 32 chars

**Single-tool design is intentional.** The server exposes only `hermes_ask(prompt, session_id?, toolsets?)`. Do not add more tools without discussing in an issue first.

## Key constraints

- `MCP_BEARER_TOKEN` is required — server refuses to start without it
- Subprocess argv is always a list; `shell=True` is never acceptable
- Prompt content must only be logged at DEBUG level, not INFO (privacy by default)
- mypy is run on `src/` only — the `mcp` package lacks stubs and is excluded
- Python ≥ 3.11 required; CI tests 3.11 and 3.12

## Release process

Bump version in `src/hermes_mcp/__init__.py` and `pyproject.toml`, move Unreleased section in `CHANGELOG.md` to the new version, tag `v0.X.Y`, push. GitHub Actions publishes to PyPI via trusted publishing.
