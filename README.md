# hermes-mcp

> An MCP server that lets **Claude Desktop** and the **Claude mobile app** delegate tasks to a local **[Hermes Agent](https://github.com/hermes-agent/hermes-agent)** running on your own hardware.

Use Claude as your daily chat. When you ask for something Hermes is built for — scheduling cron jobs, browser automation, email, document creation, persistent skills, WhatsApp/Slack messaging — Claude calls Hermes through this bridge.

```
┌──────────────────────┐     ┌────────────────────────┐
│ Claude Desktop       │     │ Claude Android / iOS   │
│ (laptop)             │     │ (phone)                │
└──────────┬───────────┘     └──────────┬─────────────┘
           │ HTTPS (Custom Connector + OAuth 2.1)      │
           └────────────────┬──────────────────────────┘
                            ▼
                ┌──────────────────────┐
                │ cloudflared tunnel   │  (public HTTPS edge)
                └──────────┬───────────┘
                           │
                           ▼ localhost:8765
                ┌──────────────────────┐
                │ hermes-mcp           │  (FastMCP, Streamable HTTP)
                │ - OAuth 2.1 + PKCE   │
                │ - HTTP -> gateway    │
                └──────────┬───────────┘
                           │ HTTP /v1/chat/completions
                           ▼ localhost:8642
                ┌──────────────────────┐
                │ hermes-gateway       │  (the running Hermes brain;
                │                      │   same agent loop Telegram uses)
                └──────────────────────┘
```

## Quickstart

These steps assume you already have **Hermes Agent** installed and working on a Linux/WSL machine, with the gateway listening on `127.0.0.1:8642`.

```bash
# 1. Install
pipx install hermes-mcp

# 2. Mint OAuth client credentials
hermes-mcp mint-client                  # prints OAUTH_CLIENT_ID + OAUTH_CLIENT_SECRET

# 3. Start a quick tunnel (testing only — URL changes on restart)
cloudflared tunnel --url http://127.0.0.1:8765
# prints: https://random-words-here.trycloudflare.com

# 4. Export env vars (using the URL from step 3)
export OAUTH_CLIENT_ID=<from step 2>
export OAUTH_CLIENT_SECRET=<from step 2>
export OAUTH_ISSUER_URL=https://random-words-here.trycloudflare.com
export MCP_ALLOWED_HOSTS=random-words-here.trycloudflare.com
export HERMES_API_KEY=<the API_SERVER_KEY from ~/.hermes/.env>

# 5. Verify everything is wired up
hermes-mcp doctor

# 6. Run
hermes-mcp serve
```

In Claude Desktop (or the mobile app), **Settings → Connectors → Add custom connector** → paste `<tunnel-url>/mcp`, then your `OAUTH_CLIENT_ID` and `OAUTH_CLIENT_SECRET`. Claude completes the OAuth flow itself.

Once you've confirmed it works end-to-end, follow the [named tunnel](#named-tunnel-for-keeping-it) and [systemd](#running-as-a-service-on-the-mini-pc) sections to make it permanent.

Try asking: *"Use Hermes to schedule a daily cron job that emails me a summary of my inbox at 8am."*

---

## Configuration

All settings via environment variables. See [`.env.example`](.env.example) for the canonical list.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `OAUTH_CLIENT_ID` | **yes** | — | Static OAuth 2.1 client ID. Generate with `hermes-mcp mint-client`. |
| `OAUTH_CLIENT_SECRET` | **yes** | — | Static OAuth 2.1 client secret (≥32 chars). Generate with `hermes-mcp mint-client`. |
| `OAUTH_ISSUER_URL` | **yes** | — | Public HTTPS URL where the server is reachable (your tunnel hostname). |
| `HERMES_API_KEY` | **yes** | — | Bearer token for the local Hermes gateway's OpenAI-compatible API (the `API_SERVER_KEY` from `~/.hermes/.env`). |
| `HERMES_API_URL` | no | `http://127.0.0.1:8642` | Base URL of the running Hermes gateway. |
| `HERMES_MODEL` | no | `hermes-agent` | Model identifier sent to `/v1/chat/completions`. |
| `MCP_ALLOWED_HOSTS` | no | (localhost only) | Comma-separated additional Host header values to accept (typically your public tunnel hostname). MCP uses this for DNS-rebinding protection. |
| `BIND_HOST` | no | `127.0.0.1` | Bind address. The tunnel reaches it on localhost. **Do not** bind `0.0.0.0` unless you understand the implications. |
| `BIND_PORT` | no | `8765` | Port. |
| `HERMES_REQUEST_TIMEOUT_SECONDS` | no | `300` | Max wall-clock per `hermes_ask` call. |
| `LOG_LEVEL` | no | `INFO` | `DEBUG` enables prompt-body logging. |

## What Claude sees

The MCP server exposes one tool:

### `hermes_ask(prompt, session_id?, toolsets?)`

Delegates a task to Hermes. Use it for anything Claude cannot do directly:

- Scheduling cron jobs / recurring tasks
- Browser-driven web search and scraping
- Sending email
- Creating, saving, or editing local documents
- Anything that should persist after this chat ends (Hermes memory, skills)
- Sending WhatsApp / Slack messages via Hermes's messaging gateway

Pass the same `session_id` across calls within one Claude chat to let Hermes build on previous steps (draft → refine → save). It is forwarded as the `X-Hermes-Session-Id` header so Hermes threads the call into an existing session.

The `toolsets` argument is accepted for backward compatibility but is currently ignored — toolset selection now lives in your Hermes config (`platform_toolsets.api_server`). Set it there to match the Telegram surface (typically `[hermes-telegram]`) so Claude gets the same tools the Telegram path does.

## Network exposure: `cloudflared`

Recommended. Free, open-source, no bandwidth cap that matters at personal scale.

There are two flavors. Use the **quick tunnel** to test today; use the **named tunnel** for any setup you want to leave running.

### Quick tunnel (for testing)

Throwaway URL, no Cloudflare account needed, dies on `cloudflared` restart. Perfect for the first end-to-end test.

```bash
# 1. Install cloudflared
sudo apt install cloudflared        # or download from cloudflare.com

# 2. Run a quick tunnel pointed at the local bridge
cloudflared tunnel --url http://127.0.0.1:8765
```

`cloudflared` prints a URL like `https://random-words-here.trycloudflare.com`. That's your tunnel for as long as the process runs. Use it as the connector URL in Claude:

```
Connector URL:  https://random-words-here.trycloudflare.com/mcp
Client ID:      <from `hermes-mcp mint-client`>
Client Secret:  <from `hermes-mcp mint-client`>
```

Set `OAUTH_ISSUER_URL` to `https://random-words-here.trycloudflare.com` and add the hostname to `MCP_ALLOWED_HOSTS` so MCP's DNS-rebinding check accepts it.

⚠ Quick tunnels are ephemeral. The hostname changes every restart — Claude's connector breaks every time. Move to a named tunnel as soon as you're past the smoke test.

### Named tunnel (for keeping it)

Stable hostname on a Cloudflare-managed domain. Survives reboots.

**Prerequisite:** a domain on Cloudflare DNS. Easiest is registering one through [Cloudflare Registrar](https://dash.cloudflare.com/?to=/:account/domains/register) (~$10/yr, sold at cost). If you already have a domain elsewhere, change its nameservers at the registrar to the two Cloudflare gives you, wait for the zone to go Active, then continue. **Don't** put your primary domain on Cloudflare DNS without first auditing email/Workspace records — you'll need to verify Cloudflare's auto-import covers MX, SPF, DKIM, and DMARC before changing nameservers. Buying a separate cheap domain just for the tunnel is the boring safe move.

```bash
# 1. Authorize this machine on your Cloudflare account (interactive: opens a URL)
cloudflared tunnel login

# 2. Create the tunnel — pick any name, e.g. "hermes"
cloudflared tunnel create hermes

# 3. Route a DNS hostname to it (requires the domain be on Cloudflare DNS)
cloudflared tunnel route dns hermes hermes.your-domain.example

# 4. Configure ~/.cloudflared/config.yml
cat > ~/.cloudflared/config.yml <<EOF
tunnel: <UUID-from-step-2>
credentials-file: $HOME/.cloudflared/<UUID-from-step-2>.json
ingress:
  - hostname: hermes.your-domain.example
    service: http://127.0.0.1:8765
  - service: http_status:404
EOF

# 5. Test it
cloudflared tunnel run hermes
# In another terminal:
#   curl -sS https://hermes.your-domain.example/.well-known/oauth-authorization-server
#   ⇒ should print the OAuth metadata JSON
```

Your stable URL is now `https://hermes.your-domain.example`. Update Claude's connector to `<URL>/mcp`, set `OAUTH_ISSUER_URL` to the URL, and add `hermes.your-domain.example` to `MCP_ALLOWED_HOSTS`.

Run cloudflared as a systemd user service — see [`deploy/cloudflared.service`](deploy/cloudflared.service):

```bash
mkdir -p ~/.config/systemd/user
cp deploy/cloudflared.service ~/.config/systemd/user/cloudflared.service
systemctl --user daemon-reload
systemctl --user enable --now cloudflared.service
journalctl --user -u cloudflared -f
```

## Alternative tunnel: `ngrok`

Equally valid; pick this if you already have an ngrok account and don't want to set up Cloudflare DNS.

```bash
ngrok config add-authtoken <your-token>

# Free tier includes one stable static domain
ngrok http 8765 --domain=your-name.ngrok-free.app
```

A systemd unit is provided in [`deploy/ngrok.service`](deploy/ngrok.service).

## Adding the connector in Claude

**Claude Desktop:** Settings → Connectors → Add custom connector → paste `<tunnel-url>/mcp` → paste your `OAUTH_CLIENT_ID` and `OAUTH_CLIENT_SECRET`. Claude completes the OAuth 2.1 authorization-code flow with PKCE automatically.

**Claude mobile app:** same flow under Settings → Connectors. The connector you add is per-account, so it works on both Desktop and mobile from one configuration.

> Screenshots are coming once we cut a v0.1.0 release. PRs welcome.

## Running as a service on the mini-PC

Install [`deploy/hermes-mcp.service`](deploy/hermes-mcp.service) as a **systemd user unit** so it shares the lifecycle of your other personal services (e.g. `hermes-gateway`, `mcp-proxy`):

```bash
# 1. Install hermes-mcp on a stable path
pipx install hermes-mcp

# 2. Set up the env file (mode 0600)
mkdir -p ~/.config/hermes-mcp
install -m 0600 .env.example ~/.config/hermes-mcp/env
$EDITOR ~/.config/hermes-mcp/env       # fill in OAUTH_*, HERMES_API_KEY, etc.

# 3. Install the unit
mkdir -p ~/.config/systemd/user
cp deploy/hermes-mcp.service ~/.config/systemd/user/

# 4. Make sure user services start at boot, not just login
loginctl enable-linger "$USER"

# 5. Enable + start
systemctl --user daemon-reload
systemctl --user enable --now hermes-mcp
journalctl --user -u hermes-mcp -f
```

Restart after editing the env file: `systemctl --user restart hermes-mcp`.

## Security

**This bridge lets a remote LLM run actions on your machine via Hermes.** Treat it accordingly. Full threat model in [THREAT_MODEL.md](THREAT_MODEL.md). In short:

- **Do not run Hermes with `--yolo`.** Keep approval hooks on.
- **Scope `platform_toolsets.api_server`** in your Hermes config to the minimum toolset your use case needs (see [What Claude sees](#hermes_askprompt-session_id-toolsets)).
- **The OAuth `client_secret` and `HERMES_API_KEY` are credentials.** A leaked `client_secret` lets an attacker mint access tokens against your bridge; a leaked `HERMES_API_KEY` lets them bypass the bridge and call the gateway directly. Rotate (`hermes-mcp mint-client` for OAuth; edit `API_SERVER_KEY` in `~/.hermes/.env` for the gateway) if exposed.
- **Prompt injection is real.** A malicious prompt slipping into Claude's context (via a webpage, a file you pasted) can craft tool calls. Hermes's own approval hooks are your last line of defense — keep them on.

Code-side mitigations baked in:

- OAuth 2.1 with mandatory PKCE-S256. `client_secret` comparison via `hmac.compare_digest`. Authorization codes are single-use with atomic pop-on-exchange; refresh tokens rotate atomically and approximate RFC 6819 reuse detection.
- `redirect_uri` scheme allowlist on `/authorize` (https, http-on-localhost, claude, claudeai) prevents the bridge becoming an open redirector to `javascript:` / `data:` URIs.
- Access tokens are 256-bit `secrets.token_urlsafe`, expire after 1 hour, live only in memory (no on-disk persistence). Refresh tokens 30d, also in memory.
- DNS-rebinding protection via `MCP_ALLOWED_HOSTS` enforced at the transport layer.
- Prompt bodies and gateway response bodies logged only at `DEBUG`. INFO logs are endpoint + length + session_id + duration only. The OAuth `state` parameter is sanitized before logging.
- Bind defaults to `127.0.0.1`; non-loopback `BIND_HOST` triggers a startup warning.
- **No telemetry, ever.** Your prompts go Claude → tunnel edge → bridge → gateway. Nothing else.

## Common pitfalls

- **`hermes-mcp doctor` reports "hermes gateway unreachable"** → the gateway isn't running. `systemctl --user status hermes-gateway` will tell you why.
- **`doctor` reports "rejected the API key (401)"** → `HERMES_API_KEY` doesn't match `API_SERVER_KEY` in `~/.hermes/.env`. Update one or the other and restart.
- **Connector stuck on "Verifying"** → 9 times out of 10 it's a wrong `client_id` or `client_secret`, or `OAUTH_ISSUER_URL` doesn't match the URL you pasted into Claude. They must be the same hostname.
- **"Invalid Host header" / 421** → your tunnel hostname isn't in `MCP_ALLOWED_HOSTS`. Add it (comma-separated) and restart.
- **Cloudflared 502** → `hermes-mcp` isn't running. `journalctl --user -u hermes-mcp` will tell you why.
- **Restart invalidates Claude's tokens** → expected; refresh tokens are in-memory. Claude's next call triggers a transparent re-auth using the long-lived `client_secret`. If that also fails (e.g., refresh token expired), open the connector once in Claude Desktop to re-authorize.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

Apache-2.0. See [LICENSE](LICENSE).

## Status

This is an unofficial bridge. It is not affiliated with or endorsed by the Hermes Agent project, and not affiliated with Anthropic.
