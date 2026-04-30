---
name: codex-imagegen-discord
description: "Generate an image via Codex CLI ($imagegen) or OpenClaw (gpt-image-2), save it to disk, and post it to Discord. Supports three upload transports — webhook (simplest), bot token, or OpenClaw adapter. Use when the user asks to: (1) generate an image with Codex CLI or OpenClaw, (2) post it to Discord from any CLI agent (Claude Code / Codex CLI / OpenClaw), (3) save-to-file then post-to-Discord."
---

# imagegen → save → post to Discord

> Source / updates: https://github.com/ryan4559/codex-imagegen-discord

## Requirements

- **Python 3.10+** and **`curl`** on PATH
- **A generation provider** (one of):
  - **Codex CLI** — `codex login` (`~/.codex/auth.json` exists); `image_generation` feature enabled (`codex features list | grep image_generation` → `true`)
  - **OpenClaw** — `openclaw` CLI on PATH with image generation support (gpt-image-2); images saved to `~/.openclaw/media/tool-image-generation/`
- **Exactly one Discord transport** (see table below)
- **Linux only**: install `bubblewrap` (`sudo apt install bubblewrap`) to silence Codex's sandbox warning. Not required — Codex falls back to a vendored `bwrap`. macOS uses `sandbox-exec` and doesn't need this. On Windows, use WSL2.

> ⚠️ `$imagegen` turns consume your **ChatGPT plan** quota at roughly **3–5× the tokens of a normal turn**. To bill via API instead, set `OPENAI_API_KEY`.

## Transports

Control with `--transport {auto,webhook,bot,openclaw}`. Auto-detected from env vars.

| Transport | Env / Setup | Supports |
|---|---|---|
| **webhook** (simplest) | `DISCORD_WEBHOOK_URL` — see [`references/setup-webhook.md`](references/setup-webhook.md) | Post to one channel only. **Cannot** read history, DM users, or use `--use-latest-discord-image`. |
| **bot** | `DISCORD_BOT_TOKEN` + a bot invited to the server — see [`references/setup-bot.md`](references/setup-bot.md) | Full features: multi-channel, DMs (`user:<id>`), edit-from-latest. |
| **openclaw** | `openclaw` CLI on PATH with a configured Discord adapter | Full features via OpenClaw. |

**Auto-detection order** (`--transport auto`, default): `DISCORD_WEBHOOK_URL` → `DISCORD_BOT_TOKEN` → `openclaw` on PATH → error. First one present wins.

## Usage

Pick an output path inside a writable tmp directory (timestamped to avoid clobbering):

```bash
OUT=~/tmp/codex-img-$(date +%Y%m%d-%H%M%S).png
```

**Webhook** (no `--target` needed — URL already pins the channel):
```bash
python3 path/to/scripts/codex_imagegen_to_discord.py \
  --prompt "<image prompt>" --out "$OUT"

**Aspect ratio / size**:

- You can force size with `--size 1536x1024` / `--size 1024x1536`.
- Or pass `--aspect 16:9` / `--aspect 9:16`.
- If you pass neither, the script will try to infer `ratio/aspect` patterns from `--prompt` (e.g. `ratio 16:9`) and choose a best-effort supported size; otherwise it defaults to `1024x1024`.
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
- **Image is written to `--out` before upload**, so a failed upload doesn't lose the image — fix the transport and re-upload by hand.
- **`--out`** is always required and decided by the calling agent. When using openclaw transport, point it to `~/.openclaw/media/tool-image-generation/<name>.png` to align with OpenClaw's media storage convention.
- **Working directory** (for `codex exec --cd`): defaults to `$OPENCLAW_WORKSPACE`, otherwise `~/.openclaw/workspace`. Override with `--cd`.

## When things go wrong

See [`references/troubleshooting.md`](references/troubleshooting.md) for error-by-error fixes (Codex generation failures, Discord permission errors, C2PA / content credentials stripped on upload, etc.).
