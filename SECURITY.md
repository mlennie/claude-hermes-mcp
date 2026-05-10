# Security Policy

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems.

Use **GitHub's private vulnerability reporting** instead: go to the [Security tab](https://github.com/mlennie/claude-hermes-mcp/security) of this repository and click **"Report a vulnerability"**. This opens a private advisory thread visible only to you and the maintainers.

Please include:

- A description of the issue.
- Steps to reproduce.
- The version of `hermes-mcp` affected.
- Your contact info if you'd like credit in the changelog.

You should expect an acknowledgement within 7 days. Please give us 90 days to ship a fix before public disclosure.

## Supported versions

Security fixes land on the latest minor release. There is no LTS branch.

## Threat model

For the full threat model — including adversary scenarios, design rationale, and residual risks — see [THREAT_MODEL.md](THREAT_MODEL.md). The summary below is a quick reference.

`hermes-mcp` is an OAuth-gated bridge: Claude.ai → cloudflared/ngrok tunnel → hermes-mcp on `127.0.0.1:8765` → HTTP `/v1/chat/completions` → `hermes-gateway` on `127.0.0.1:8642` → AIAgent loop. The bridge holds two long-lived secrets: an OAuth `client_secret` (used by Claude to obtain access tokens) and `HERMES_API_KEY` (used by the bridge to authenticate to the gateway). Compromise of either one is equivalent to **remote action execution on the host** at the privileges of the user running the gateway.

### Trust boundaries

| Component | Trust | Notes |
|---|---|---|
| Host OS / shell | Trusted | If this is compromised, all bets are off. |
| `hermes-mcp` server | Trusted | Code under this repo. |
| `hermes-gateway` server | Trusted | Separate process owned by the same user. The bridge has no sandbox around it. |
| Tunnel edge (cloudflared / ngrok) | Trusted transport | TLS termination at the edge; we trust them not to MITM. |
| `OAUTH_CLIENT_SECRET` | Sensitive credential | Treat as a password. Pasted into Claude Desktop. |
| `HERMES_API_KEY` | Sensitive credential | Bearer to the gateway. Never leaves the host. |
| Claude client (Desktop / mobile) | Authenticated | Holds the OAuth credentials and minted access tokens. |
| Prompts arriving at `hermes_ask` | **Untrusted input** | May be poisoned by injection upstream. |

### Top risks

1. **OAuth credential leak.** `OAUTH_CLIENT_SECRET` exposure is a full compromise — an attacker can mint access tokens via the OAuth flow without further interaction. Mitigations: `hermes-mcp mint-client` produces a ≥40-char `secrets.token_urlsafe` value; configuration enforces ≥32 characters; `hmac.compare_digest` for the `/token` comparison eliminates timing extraction. Rotate (`hermes-mcp mint-client`, edit env, `systemctl --user restart hermes-mcp`) if exposed.

2. **Gateway API-key leak.** `HERMES_API_KEY` lets anyone on the host (or its loopback namespace) bypass the bridge entirely and call `/v1/chat/completions` directly. Mitigations: `0600` permissions on `~/.config/hermes-mcp/env`. Run `hermes-mcp` and `hermes-gateway` as a dedicated low-privilege user with no other co-tenants.

3. **Prompt injection via Claude's context.** A webpage or pasted file in a Claude chat tells Claude to call `hermes_ask` with malicious instructions. Mitigations are mostly upstream and user-side:
   - Keep Hermes's approval hooks on. Do **not** run with `--yolo`.
   - Configure `platform_toolsets.api_server` in your Hermes config to a narrowly scoped toolset.
   - This bridge cannot reliably detect injection. The user controls Hermes's authorization model.

4. **Authorization-code interception.** Mitigated by mandatory PKCE-S256 and the requirement that `client_secret` accompany the code exchange at `/token`. Codes are single-use (atomic pop on exchange), expire in 60 seconds, and `_StaticClient.validate_redirect_uri` enforces a scheme allowlist (`https`, `http` for localhost only, `claude`, `claudeai`) to prevent `/authorize` becoming an open redirector.

5. **Refresh-token replay.** Mitigated by atomic-pop-then-mint rotation: a second concurrent `/token` request with the same refresh token finds it gone and is rejected. This also approximates RFC 6819 reuse detection.

6. **DoS via unbounded state growth.** `/authorize` is a public endpoint. Mitigated by `MAX_OUTSTANDING_AUTH_CODES` and `MAX_OUTSTANDING_ACCESS_TOKENS` caps with opportunistic reaping of expired entries.

7. **Information disclosure via logs.** Prompt bodies and gateway response bodies are logged only at `DEBUG`. The default `INFO` level logs only `endpoint`, `prompt_chars`, session presence, and timeouts. Token-mint events log only the TTL. The OAuth `state` parameter is sanitized (newlines escaped, truncated) before logging to prevent log injection. Tunnel access logs may record IP and request volume; they do not see request bodies because TLS terminates there before the body is forwarded to the local server.

### Out of scope for the threat model

- Compromise of the host operating system.
- Compromise of the cloudflared / ngrok account or their infrastructure.
- Compromise of the user's Claude account (which would let an attacker into the same chats anyway).
- Compromise of the `hermes-gateway` process itself (Scenario E in THREAT_MODEL.md).

## No telemetry

`hermes-mcp` makes **no outbound network requests** other than what your tunnel software does and what Hermes itself does. No analytics, no error reporting, no version-check pings. If we ever add anything optional, it will be off by default and called out loudly here.
