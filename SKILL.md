---
name: codex-imagegen-discord
description: "Generate an image via Codex CLI ($imagegen) using the host's existing Codex login (no OPENAI_API_KEY), save it to disk, and post it to Discord. Supports three upload transports — webhook (simplest), bot token, or OpenClaw adapter. Use when the user asks to: (1) generate an image with Codex CLI, (2) post it to Discord from any CLI agent (Claude Code / Codex CLI / OpenClaw), (3) save-to-file then post-to-Discord."
---

# Codex imagegen → save → post to Discord

> Source / updates: https://github.com/ryan4559/codex-imagegen-discord

## Requirements

- **Python 3.10+** and **`curl`** on PATH
- **Codex CLI signed in** (`codex login`; `~/.codex/auth.json` exists)
- **`image_generation` feature enabled** (`codex features list | grep image_generation` → `true`; stable default)
- **Exactly one Discord transport** (see table below)
- **Linux only**: install `bubblewrap` (`sudo apt install bubblewrap`) to silence Codex's sandbox warning. Not required — Codex falls back to a vendored `bwrap`. macOS uses `sandbox-exec` and doesn't need this. On Windows, use WSL2.

## Transports

The script uploads the generated PNG via one of three transports. Auto-detected from env vars, or force with `--transport {webhook,bot,openclaw}`.

| Transport | Env / Setup | Supports |
|---|---|---|
| **webhook** (simplest) | `DISCORD_WEBHOOK_URL` — see [`references/setup-webhook.md`](references/setup-webhook.md) | Post to one channel only. **Cannot** read history, DM users, or use `--use-latest-discord-image`. |
| **bot** | `DISCORD_BOT_TOKEN` + a bot invited to the server — see [`references/setup-bot.md`](references/setup-bot.md) | Full features: multi-channel, DMs (`user:<id>`), edit-from-latest. |
| **openclaw** (legacy) | `openclaw` CLI on PATH with a configured Discord adapter | Full features via OpenClaw. |

**Auto-detection order** (`--transport auto`, default): `DISCORD_WEBHOOK_URL` → `DISCORD_BOT_TOKEN` → `openclaw` on PATH → error. First one present wins.

> ⚠️ `$imagegen` turns consume your **ChatGPT plan** quota at roughly **3–5× the tokens of a normal turn**. To bill via API instead, set `OPENAI_API_KEY`.

## Usage

Pick an output path inside a writable tmp directory (timestamped to avoid clobbering):

```bash
OUT=~/tmp/codex-img-$(date +%Y%m%d-%H%M%S).png
```

**Webhook** (no `--target` needed — URL already pins the channel):
```bash
python3 path/to/scripts/codex_imagegen_to_discord.py \
  --prompt "<image prompt>" --out "$OUT"
```

**Bot / OpenClaw** (need `--target`):
```bash
python3 path/to/scripts/codex_imagegen_to_discord.py \
  --prompt "<image prompt>" --out "$OUT" \
  --target "channel:<id>"        # or user:<id> for DM (bot/openclaw only)
```

### Edit / extend an existing image

All reference flags are **repeatable** — pass multiple to give Codex several references in one turn (e.g. `-i a.png -i b.jpg`, or mix local / URL / latest).

**Option A** — auto-grab the channel's most recent image attachment (**bot or openclaw only**; webhook can't read history):
```bash
python3 path/to/scripts/codex_imagegen_to_discord.py \
  --use-latest-discord-image \
  --prompt "<what to change>" --out "$OUT" --target "channel:<id>"
```

**Option B** — pass a Discord CDN URL explicitly (works with **any** transport; only `cdn.discordapp.com` / `media.discordapp.net` hosts are allowed, SSRF guard):
```bash
python3 path/to/scripts/codex_imagegen_to_discord.py \
  --image-url "https://cdn.discordapp.com/.../your.png" \
  --prompt "<what to change>" --out "$OUT"
```

**Option C** — pass local file path(s) with `-i` / `--image` (works with **any** transport):
```bash
python3 path/to/scripts/codex_imagegen_to_discord.py \
  -i ~/refs/style.png -i ~/refs/subject.jpg \
  --prompt "combine style of first with subject of second" --out "$OUT"
```

## Notes

- `--target` is required for bot / openclaw; ignored by webhook (the URL already pins a channel).
- **No `OPENAI_API_KEY` needed** — the flow relies on `codex login` ("Sign in with ChatGPT"). Setting `OPENAI_API_KEY` switches billing to the API instead of your ChatGPT plan quota.
- **PNG is written to `--out` before upload**, so a failed upload doesn't lose the image — fix the transport and re-upload by hand.
- **Working directory** (for `codex exec --cd`): defaults to `$OPENCLAW_WORKSPACE`, otherwise `~/.openclaw/workspace`. Override with `--cd`.

## When things go wrong

See [`references/troubleshooting.md`](references/troubleshooting.md) for error-by-error fixes (Codex generation failures, Discord permission errors, C2PA / content credentials stripped on upload, etc.).
