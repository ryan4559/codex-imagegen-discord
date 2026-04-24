# Troubleshooting

## Transport / setup errors

**`No transport available`**  
Set exactly one of `DISCORD_WEBHOOK_URL` / `DISCORD_BOT_TOKEN` / have `openclaw` on PATH, or pass `--transport <name>` explicitly. See `setup-webhook.md` or `setup-bot.md`.

**`--use-latest-discord-image is not supported with webhook transport`**  
Webhooks can't read channel history. Options: switch to bot transport, use OpenClaw, or pass `--image-url` with a Discord CDN link you already have.

**`--transport bot requires --target`**  
Bot transport needs to know which channel / user to post to. Pass `--target channel:<id>` or `--target user:<id>`.

## Codex generation errors

**`no new PNG appeared under ~/.codex/generated_images`**
1. Confirm `codex features list | grep image_generation` reports `true` (stable default).
2. Confirm the host is signed in (`~/.codex/auth.json` exists, or re-run `codex login`).
3. Sanity check by hand: `codex exec --skip-git-repo-check '$imagegen a red circle'` — does a new file appear?

**`codex exec exceeded 600s; aborting`**  
The turn genuinely hung. The script fails immediately rather than retrying, so it does **not** chain-burn quota. Investigate before rerunning.

## Discord upload errors

**`Failed to optimize image`** (any transport)  
The script automatically retries as a `.dat` attachment — Discord keeps the bytes but stores it as a generic file; the message notes how to rename back to `.png` after download.

**`Missing Permissions` / `Missing Access`** (bot transport)  
The bot needs `Send Messages` + `Attach Files` on the channel, and (for `--use-latest-discord-image`) `Read Message History` + `View Channel`. Re-invite via `OAuth2 URL Generator` with the right permission bits, or have a server admin grant them in the channel settings.

**`Unknown Channel`** (bot transport, HTTP 404)  
The channel ID is wrong, or the bot hasn't been invited to that server. Double-check the ID (Developer Mode → right-click channel → Copy Channel ID) and confirm the bot appears in the server member list.

**`401 Unauthorized`** (bot transport)  
`DISCORD_BOT_TOKEN` is invalid or revoked. Reset it in the Developer Portal (`Bot` → `Reset Token`) and update the env var.

**`50007 Cannot send messages to this user`** (bot transport, `user:<id>`)  
The user has DMs disabled for your bot's servers, or you don't share a guild with them. DMs require: (1) shared guild between bot and user, (2) user's privacy setting allowing DMs from server members.

## C2PA / content credentials

**"My image doesn't verify on contentcredentials.org after I post it to Discord"**  
Every PNG `$imagegen` produces carries a C2PA manifest (a `caBX` chunk, ~26 KB) that identifies it as OpenAI-generated. **Discord strips it on upload** regardless of filename or extension — it sniffs content and re-encodes (empirically tested: `.dat` suffix and even extensionless files get renamed to `.png` and transcoded to JPEG). If you need the signed original, grab it straight from `~/.codex/generated_images/<session>/ig_*.png` — the script also writes a bit-identical copy to your `--out` path before uploading.
