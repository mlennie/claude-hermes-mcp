---
name: Bug report
about: Something isn't working
labels: bug
---

## Versions

| Component | Version |
|---|---|
| hermes-mcp | |
| Hermes Agent (`hermes --version`) | |
| Python (`python --version`) | |
| OS / distro | |

## Setup

- **Tunnel type:** <!-- cloudflared / ngrok / other / none (local only) -->
- **Claude client:** <!-- Claude Desktop / Claude Mobile / API direct -->
- **HERMES_TOOLSETS set?** <!-- yes (list them) / no -->
- **Custom HERMES_BIN?** <!-- yes / no (using PATH) -->

## What happened

<!-- What did you observe? -->

## What you expected

<!-- What should have happened instead? -->

## Steps to reproduce

1.
2.
3.

## Doctor output

```
# Run: hermes-mcp doctor
# Paste the full output here
```

## Relevant logs

```
# Run: LOG_LEVEL=DEBUG hermes-mcp serve  (or journalctl -u hermes-mcp -n 100)
# Redact your bearer token and any sensitive prompt content before pasting.
```

## What you've already tried

<!-- Saves everyone time -->
