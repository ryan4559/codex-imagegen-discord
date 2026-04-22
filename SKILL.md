---
name: codex-imagegen-discord
description: "Generate an image via Codex CLI ($imagegen) using the host's existing Codex login (no OPENAI_API_KEY), save it to the OpenClaw workspace, and upload it back to the current Discord channel (or a specified target). Use when the user asks to: (1) generate an image with Codex CLI, (2) do it from Discord/ACP without typing long commands, (3) save-to-file then post-to-Discord."
---

# Codex imagegen → save → post to Discord

## Requirements

| Item | How to verify | Required? |
|---|---|---|
| **Python 3.10+** | `python3 --version` (script uses `list[str]` / `X \| None` syntax) | Yes |
| **Codex CLI signed in** | Run `codex login` once; `~/.codex/auth.json` exists | Yes |
| **`image_generation` feature** | `codex features list \| grep image_generation` reports `true` (stable default) | Yes |
| **OpenClaw with Discord channel** | `openclaw message send --channel discord ...` succeeds | Yes |
| **bubblewrap (`bwrap`)** | `which bwrap`; on Debian/Ubuntu: `sudo apt install bubblewrap` | Recommended — without it Codex falls back to a vendored binary and prints a warning, but still runs |

**Working directory** (for `codex exec --cd`): defaults to `$OPENCLAW_WORKSPACE`, otherwise `~/.openclaw/workspace`. Override with `--cd`.

**Note on bubblewrap**: Codex uses `bwrap` to sandbox shell commands the model issues at runtime. This skill only invokes `$imagegen` (no shell tool calls), so bubblewrap is initialized but effectively unused. If it's missing, Codex falls back to a vendored copy and prints a one-line warning — everything still works. Installing the system package just silences the warning and is good hygiene for other Codex workflows that *do* run commands.

> ⚠️ `$imagegen` turns consume your **ChatGPT plan** quota at roughly **3–5× the tokens of a normal turn**. To bill via API instead, set `OPENAI_API_KEY`.

## Quick usage (when the user in Discord asks "generate an image with Codex")

1) Pick an output file path inside the workspace (avoids writing to random system locations):
- Suggested: `~/.openclaw/workspace/tmp/codex-img.png`
- Or timestamp to avoid clobbering: `.../tmp/codex-img-YYYYMMDD-HHMMSS.png`

2) Run the script. It will: invoke `codex exec $imagegen` → snapshot `~/.codex/generated_images/` → pick the newest PNG that appeared → upload via `openclaw message send`.

```bash
python3 ~/.openclaw/workspace/skills/codex-imagegen-discord/scripts/codex_imagegen_to_discord.py \
  --prompt "<image prompt>" \
  --out "~/.openclaw/workspace/tmp/codex-img.png" \
  --target "<discord target: channel:... or user:...>"
```

### Using an existing Discord image as a reference (edit / extend)

**Option A (easiest)** — use the channel's most recent image attachment as the reference:

```bash
python3 ~/.openclaw/workspace/skills/codex-imagegen-discord/scripts/codex_imagegen_to_discord.py \
  --use-latest-discord-image \
  --prompt "<what to change>" \
  --out "~/.openclaw/workspace/tmp/codex-img.png" \
  --target "channel:..."
```

**Option B** — you already have a Discord CDN URL (only `cdn.discordapp.com` / `media.discordapp.net` are allowed, to prevent SSRF):

```bash
python3 ~/.openclaw/workspace/skills/codex-imagegen-discord/scripts/codex_imagegen_to_discord.py \
  --image-url "https://cdn.discordapp.com/.../your.png" \
  --prompt "<what to change>" \
  --out "~/.openclaw/workspace/tmp/codex-img.png" \
  --target "channel:..."
```

## About C2PA provenance

Every PNG `$imagegen` produces carries a C2PA manifest (a `caBX` chunk, ~26 KB) that can be verified at contentcredentials.org/verify as OpenAI-generated. **Discord strips it on upload** regardless of filename or extension — it sniffs content and re-encodes (empirically tested: `.dat` suffix and even extensionless files get renamed to `.png` and transcoded to JPEG). If you need the signed original, grab it straight from `~/.codex/generated_images/<session>/ig_*.png`.

## Implementation notes

- `--target`: in a Discord event this is normally the current chat_id, e.g. `channel:<id>`.
- **No `OPENAI_API_KEY` needed** — the flow relies on the host having completed `codex login` ("Sign in with ChatGPT"). Setting `OPENAI_API_KEY` switches billing to the API instead of your plan quota.
- **How image extraction works**: Codex's built-in `$imagegen` tool writes the PNG to `~/.codex/generated_images/<session>/ig_*.png` and only references the path in the conversation — it does **not** return bytes in the final message. The script snapshots that directory before `codex exec`, then picks the newest PNG whose mtime is after the start timestamp.
- ⚠️ **Do not add `--output-schema`** to force Codex into returning `{"png_base64": "..."}`. A prior revision did exactly that, which fought the built-in imagegen tool (writes files, not text) and caused Codex to loop — each failure burned 3–5× the normal token budget.

## Troubleshooting

- **`no new PNG appeared under ~/.codex/generated_images`**:
  1. Confirm `codex features list | grep image_generation` is `true` (stable default — should be).
  2. Confirm the host is signed in (`~/.codex/auth.json` exists, or re-run `codex login`).
  3. Sanity check by hand: `codex exec --skip-git-repo-check '$imagegen a red circle'` — does a new file appear?
- **`codex exec exceeded 600s; aborting`**: the turn genuinely hung. The script fails immediately rather than retrying, so it does **not** chain-burn quota. Investigate before rerunning.
- **`Failed to optimize image` from Discord**: the script automatically retries as a `.dat` attachment (Discord keeps the bytes but stores it as a generic file; the message notes how to rename back to `.png`).
