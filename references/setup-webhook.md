# Webhook transport setup

The simplest way to get images out — no bot account, no OAuth flow, no server permissions. Downside: the webhook URL is locked to one channel and cannot read message history, so `--use-latest-discord-image` is off.

## Steps

1. In Discord, open the target channel → `Edit Channel` → `Integrations` → `Create Webhook` → copy the URL.
2. Export the URL (add to `~/.bashrc` to persist):
   ```bash
   export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/<id>/<token>"
   ```
3. Smoke test:
   ```bash
   curl -X POST "$DISCORD_WEBHOOK_URL" -F "content=hi"
   ```
   You should see `hi` appear in the channel.

## Notes

- Webhook URL grants anonymous post access to that one channel. Treat it like a secret — don't commit or paste publicly.
- To revoke: delete the webhook in the channel's Integrations panel. Creating a new one generates a new URL + token.
- Threads under the webhook's channel are reachable by appending `?thread_id=<id>` to the URL.
