# Bot transport setup

Use this if you need multiple channels, DMs, or `--use-latest-discord-image`. Heavier than webhook (needs a Discord application + server invite), but full feature parity with the OpenClaw adapter.

## Steps

1. Go to https://discord.com/developers/applications → `New Application` → name it.
2. Left sidebar → `Bot` → `Reset Token` → copy the string (only shown once). Save as `DISCORD_BOT_TOKEN`:
   ```bash
   export DISCORD_BOT_TOKEN="your-token-here"
   ```
3. `OAuth2` → `URL Generator`:
   - **Scopes**: `bot`
   - **Bot Permissions**: `Send Messages` + `Attach Files`
   - Add `Read Message History` + `View Channel` if you want `--use-latest-discord-image`
4. Open the generated URL → pick a server → authorize. Repeat for each server you want to post into (you must have admin on that server).
5. Grab the target channel ID: Discord client → `Settings` → `Advanced` → enable `Developer Mode` → right-click the channel → `Copy Channel ID`.
6. Smoke test:
   ```bash
   curl -X POST "https://discord.com/api/v10/channels/<channel_id>/messages" \
     -H "Authorization: Bot $DISCORD_BOT_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"content":"hi"}'
   ```
   `hi` should appear in the channel.

## DMs (`user:<id>` target)

The bot and the user must share at least one guild, and the user's DM settings must allow messages from that guild. The script auto-calls `POST /users/@me/channels` with `{"recipient_id": <id>}` to open the DM channel before posting.

## Permissions cheat sheet

| Feature | Bot permissions needed |
|---|---|
| Post image to a channel | `Send Messages`, `Attach Files` |
| DM a user | same as above (plus shared guild / user opt-in) |
| `--use-latest-discord-image` | add `View Channel`, `Read Message History` |

## Notes

- The token grants full bot control — never commit it or paste it anywhere public. If leaked, `Reset Token` in the Developer Portal immediately.
- Privileged Intents (`Presence`, `Server Members`, `Message Content`) are **not** required for this skill. Leave them off.
- Token appears on the `curl` command line when the script runs, so it's visible via `ps` to other local users. Fine on single-user hosts; consider isolation on multi-tenant boxes.
