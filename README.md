# hermes-mcp

> An MCP server that lets **Claude Desktop** and the **Claude mobile app** delegate tasks to a local **[Hermes Agent](https://github.com/hermes-agent/hermes-agent)** running on your own hardware.

Use Claude as your daily chat. When you ask for something Hermes is built for — scheduling cron jobs, browser automation, email, document creation, persistent skills, WhatsApp/Slack messaging — Claude calls Hermes through this bridge.

```
┌──────────────────────┐     ┌────────────────────────┐
│ Claude Desktop       │     │ Claude Android / iOS   │
│ (laptop)             │     │ (phone)                │
└──────────┬───────────┘     └──────────┬─────────────┘
           │ HTTPS (Custom Connector + Bearer)         │
           └────────────────┬──────────────────────────┘
                            ▼
                ┌──────────────────────┐
                │ cloudflared tunnel   │  (public HTTPS edge)
                └──────────┬───────────┘
                           │
                           ▼ localhost:8765
                ┌──────────────────────┐
                │ hermes-mcp           │  (FastMCP, Streamable HTTP)
                │ - bearer auth        │
                │ - subprocess wrapper │
                └──────────┬───────────┘
                           │ subprocess
                           ▼
                ┌──────────────────────┐
                │ hermes -z / --continue│  (CLI surface only)
                └──────────────────────┘
```

## Quickstart

These steps assume you already have **Hermes Agent** installed and working on a Linux/WSL machine, and that the same machine is reachable on the public internet via [`cloudflared`](#network-exposure-cloudflared) (recommended) or [`ngrok`](#alternative-tunnel-ngrok).

```bash
# 1. Install
pipx install hermes-mcp

# 2. Generate a strong bearer token
export MCP_BEARER_TOKEN=$(openssl rand -hex 32)
echo "$MCP_BEARER_TOKEN"   # save this — you'll paste it into Claude

# 3. Verify everything is wired up
hermes-mcp doctor

# 4. Run
hermes-mcp serve
```

In another terminal, expose `127.0.0.1:8765` over HTTPS via cloudflared (see below). Then in Claude Desktop or the Claude mobile app, **add a Custom Connector** pointing at your tunnel URL with the bearer token. You're done.

Try asking: *"Use Hermes to schedule a daily cron job that emails me a summary of my inbox at 8am."*

---

## Configuration

All settings via environment variables. See [`.env.example`](.env.example) for the canonical list.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `MCP_BEARER_TOKEN` | **yes** | — | HTTP bearer secret. Server refuses to start if unset. Generate with `openssl rand -hex 32`. |
| `HERMES_BIN` | no | `hermes` (PATH) | Absolute path to hermes binary if not on PATH. |
| `BIND_HOST` | no | `127.0.0.1` | Bind address. The tunnel reaches it on localhost. **Do not** bind `0.0.0.0` unless you understand the implications. |
| `BIND_PORT` | no | `8765` | Port. |
| `HERMES_TIMEOUT_SECONDS` | no | `300` | Max wall-clock per `hermes_ask` call. |
| `HERMES_TOOLSETS` | no | (Hermes default) | Comma-separated toolsets to restrict each call. |
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

Pass the same `session_id` across calls within one Claude chat to let Hermes build on previous steps (draft → refine → save).

## Network exposure: `cloudflared`

Recommended path. Free, open-source agent, no bandwidth cap that matters at personal scale.

```bash
# 1. Install cloudflared
sudo apt install cloudflared        # or download from cloudflare.com

# 2. Authorize against your Cloudflare account
cloudflared tunnel login

# 3. Create a named tunnel
cloudflared tunnel create hermes-mcp

# 4. Add a DNS route (requires any domain on Cloudflare DNS — free)
cloudflared tunnel route dns hermes-mcp hermes.your-domain.example

# 5. Configure ~/.cloudflared/config.yml
cat > ~/.cloudflared/config.yml <<EOF
tunnel: <UUID-from-step-3>
credentials-file: /home/$USER/.cloudflared/<UUID>.json
ingress:
  - hostname: hermes.your-domain.example
    service: http://127.0.0.1:8765
  - service: http_status:404
EOF

# 6. Run it
cloudflared tunnel run hermes-mcp
```

Your stable HTTPS URL is now `https://hermes.your-domain.example`. Paste it (and the bearer token) into Claude as a Custom Connector.

A systemd unit is provided in [`deploy/cloudflared.service`](deploy/cloudflared.service).

## Alternative tunnel: `ngrok`

Equally valid; pick this if you already have an ngrok account and don't want to set up Cloudflare DNS.

```bash
ngrok config add-authtoken <your-token>

# Free tier includes one stable static domain
ngrok http 8765 --domain=your-name.ngrok-free.app
```

A systemd unit is provided in [`deploy/ngrok.service`](deploy/ngrok.service).

## Adding the connector in Claude

**Claude Desktop:** Settings → Connectors → Add custom connector → paste the HTTPS URL → set the bearer token in the Authorization header.

**Claude mobile app:** same flow under Settings → Connectors. The connector you add is per-account, so it works on both Desktop and mobile from one configuration.

> Screenshots are coming once we cut a v0.1.0 release. PRs welcome.

## Running as a service on the mini-PC

Install [`deploy/hermes-mcp.service`](deploy/hermes-mcp.service) (and the cloudflared unit if you went that route):

```bash
sudo cp deploy/hermes-mcp.service /etc/systemd/system/
sudo install -m 0600 .env.example /etc/hermes-mcp.env  # then edit it
sudo systemctl daemon-reload
sudo systemctl enable --now hermes-mcp
journalctl -u hermes-mcp -f
```

## Security

**This bridge lets a remote LLM run actions on your machine via Hermes.** Treat it accordingly. Full threat model in [SECURITY.md](SECURITY.md). In short:

- **Do not run Hermes with `--yolo`.** Keep approval hooks on.
- **Scope `HERMES_TOOLSETS`** to the minimum your use case needs.
- **The bearer token is a credential.** A leaked token = remote action execution on your mini-PC. Rotate immediately if exposed.
- **Prompt injection is real.** A malicious prompt slipping into Claude's context (via a webpage, a file you pasted) can craft tool calls. Hermes's own approval hooks are your last line of defense — keep them on.

Code-side mitigations baked in:

- `subprocess.run` with argument lists; `shell=True` is never used.
- `MCP_BEARER_TOKEN` required at startup; comparison via `hmac.compare_digest`.
- Prompt bodies logged only at `DEBUG`. INFO logs are length + session_id + duration only.
- **No telemetry, ever.** Your prompts go Claude → tunnel edge → your mini-PC → Hermes. Nothing else.

## Common pitfalls

- **`hermes` not on PATH** → set `HERMES_BIN` to its absolute path.
- **Connector stuck on "Verifying"** → 9 times out of 10 it's a wrong bearer token. Re-paste it.
- **Cloudflared 502** → your `hermes-mcp` service isn't running. `journalctl -u hermes-mcp` will tell you why.
- **Cron jobs scheduled via Hermes don't fire** → check that `HERMES_HOME` in the systemd `EnvironmentFile` matches the user that owns the Hermes data directory. By default Hermes uses `$HOME/.hermes`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

Apache-2.0. See [LICENSE](LICENSE).

## Status

This is an unofficial bridge. It is not affiliated with or endorsed by the Hermes Agent project, and not affiliated with Anthropic.
