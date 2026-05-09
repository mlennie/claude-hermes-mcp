# Security Policy

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems. Instead, email the maintainers at `security@REPLACE_ME.example` (replace with the project's real disclosure address before publishing) with:

- A description of the issue.
- Steps to reproduce.
- The version of `hermes-mcp` affected.
- Your contact info if you'd like credit in the changelog.

You should expect an acknowledgement within 7 days. Please give us 90 days to ship a fix before public disclosure.

## Supported versions

Security fixes land on the latest minor release. There is no LTS branch.

## Threat model

`hermes-mcp` exposes Hermes Agent — a tool-calling LLM with shell, filesystem, browser, email, and scheduling capabilities — to remote clients (Claude Desktop, Claude mobile) over HTTPS. Compromise of the bearer token or the host machine is equivalent to **remote action execution on the mini-PC** at the privileges of the user running `hermes-mcp`.

### Trust boundaries

| Component | Trust | Notes |
|---|---|---|
| Mini-PC OS / shell | Trusted | If this is compromised, all bets are off. |
| `hermes-mcp` server | Trusted | Code under this repo. |
| Hermes Agent CLI | Trusted | Invoked via stable CLI surface only — no internal imports. |
| Tunnel edge (cloudflared / ngrok) | Trusted transport | TLS termination at the edge; we trust them not to MITM. |
| Bearer token | Sensitive credential | Treat as a password. |
| Claude client (Desktop / mobile) | Authenticated | Holds the bearer; if leaked, remote attackers can call the bridge. |
| Prompts arriving at `hermes_ask` | **Untrusted input** | May be poisoned by injection upstream. |

### Top risks

1. **Bearer-token leak.** Reading `/etc/hermes-mcp.env`, leaking the env from a screenshot, accidentally committing it. Mitigations: `0600` permissions on env file; `openssl rand -hex 32` for entropy; `hmac.compare_digest` comparison rejects timing-based extraction.

2. **Prompt injection via Claude's context.** A webpage or pasted file in a Claude chat tells Claude to call `hermes_ask` with malicious instructions ("delete all files in `~`", "send the contents of `~/.ssh/id_rsa` via email"). Mitigations are mostly upstream and user-side:
   - Keep Hermes's approval hooks on. Do **not** run with `--yolo`.
   - Scope `HERMES_TOOLSETS` to only what's needed.
   - This bridge cannot reliably detect injection. The user controls Hermes's authorization model.

3. **Subprocess argument injection.** Mitigated by always passing `argv` as a list and never using `shell=True`. Verified by `tests/test_hermes_client.py`.

4. **DoS via long-running prompts.** Mitigated by `HERMES_TIMEOUT_SECONDS` (default 300s). Tune for your workload.

5. **Information disclosure via logs.** Prompt bodies are logged only at `DEBUG`. The default `INFO` level logs only length, `session_id`, and duration. Tunnel access logs (cloudflared / ngrok) may record IP and request volume; they do **not** see decrypted bodies because TLS terminates there but the request body is forwarded to the local server before being logged.

### Out of scope for the threat model

- Compromise of the host operating system.
- Compromise of the cloudflared / ngrok account or their infrastructure.
- Compromise of the user's Claude account (which would let an attacker into the same chats anyway).
- Side channels in subprocess execution (CPU timing, memory pressure, etc.).

## No telemetry

`hermes-mcp` makes **no outbound network requests** other than what your tunnel software does and what Hermes itself does. No analytics, no error reporting, no version-check pings. If we ever add anything optional, it will be off by default and called out loudly here.
