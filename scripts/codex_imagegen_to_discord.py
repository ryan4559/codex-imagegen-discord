#!/usr/bin/env python3
"""Generate an image via Codex CLI ($imagegen) and upload it to Discord.

Codex CLI's built-in image generation tool saves images to
  ~/.codex/generated_images/<session-id>/ig_*
and references the path in the conversation. It does NOT return raw bytes in
the final message. So this script:
  1. snapshots that directory before running codex,
  2. runs `codex exec "$imagegen ..."` (no --output-schema),
  3. picks the newest image that appeared after start time,
  4. copies it to --out,
  5. uploads it to Discord via the selected transport.

Transports (pick with --transport, or auto-detect from env):
  - webhook    : POST to DISCORD_WEBHOOK_URL. Simplest; single channel only;
                 cannot read messages (so --use-latest-discord-image is off).
  - bot        : Use DISCORD_BOT_TOKEN against Discord REST API v10.
                 Supports all features; requires bot setup + invite.
  - openclaw   : Shell out to `openclaw message send`.

An earlier revision used `--output-schema` to force Codex to return
`{"png_base64": "..."}`. That fought the built-in imagegen tool (which writes
files, not text) and caused Codex to loop -- burning quota. Do not reintroduce
a schema here without redesigning the extraction path.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
DISCORD_CDN_HOSTS = {"cdn.discordapp.com", "media.discordapp.net"}
DISCORD_API = "https://discord.com/api/v10"
CODEX_IMAGES_DIR = os.path.expanduser("~/.codex/generated_images")
OPENCLAW_IMAGES_DIR = os.path.expanduser("~/.openclaw/media/tool-image-generation")
EXEC_TIMEOUT = 600  # seconds; imagegen turns are slow, but not infinite


def run(cmd: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def is_image_filename(name: str) -> bool:
    _, ext = os.path.splitext((name or "").lower())
    return ext in IMAGE_EXTS


def image_content_type(path: str) -> str:
    ext = os.path.splitext(path.lower())[1]
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(ext, "image/png")


def download_url_to_file(url: str, out_path: str) -> None:
    pu = urllib.parse.urlparse(url)
    if pu.scheme not in ("https", "http"):
        raise ValueError(f"unsupported url scheme: {pu.scheme}")
    host = (pu.hostname or "").lower()
    if host and host not in DISCORD_CDN_HOSTS:
        raise ValueError(f"refusing to download non-Discord host: {host}")

    req = urllib.request.Request(url, headers={"User-Agent": "codex-imagegen-discord/2.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    with open(out_path, "wb") as f:
        f.write(data)


# ---------------------------------------------------------------------------
# Transport selection
# ---------------------------------------------------------------------------

def resolve_transport(explicit: str) -> str:
    if explicit and explicit != "auto":
        return explicit
    if os.environ.get("DISCORD_WEBHOOK_URL"):
        return "webhook"
    if os.environ.get("DISCORD_BOT_TOKEN"):
        return "bot"
    if shutil.which("openclaw"):
        return "openclaw"
    raise SystemExit(
        "No transport available. Set one of:\n"
        "  DISCORD_WEBHOOK_URL    -- simplest; single channel; no history read\n"
        "  DISCORD_BOT_TOKEN      -- requires bot app + invite; supports all features\n"
        "  install `openclaw`     -- use the OpenClaw Discord adapter\n"
        "Or pass --transport {webhook,bot,openclaw} explicitly."
    )


def validate_transport_args(transport: str, args: argparse.Namespace) -> None:
    if transport == "webhook":
        if not os.environ.get("DISCORD_WEBHOOK_URL"):
            raise SystemExit("--transport webhook requires DISCORD_WEBHOOK_URL in env.")
        if args.use_latest_discord_image:
            raise SystemExit(
                "--use-latest-discord-image is not supported with webhook transport.\n"
                "Webhooks cannot read channel history. Use --transport bot or openclaw,\n"
                "or pass --image-url / --image with an explicit reference."
            )
    elif transport == "bot":
        if not os.environ.get("DISCORD_BOT_TOKEN"):
            raise SystemExit("--transport bot requires DISCORD_BOT_TOKEN in env.")
        if not args.target:
            raise SystemExit("--transport bot requires --target (channel:<id> or user:<id>).")
    elif transport == "openclaw":
        if not shutil.which("openclaw"):
            raise SystemExit("--transport openclaw requires the `openclaw` CLI on PATH.")
        if not args.target:
            raise SystemExit("--transport openclaw requires --target (channel:<id> or user:<id>).")
    else:
        raise SystemExit(f"Unknown transport: {transport!r}")


# ---------------------------------------------------------------------------
# Discord API helpers (bot transport)
# ---------------------------------------------------------------------------

def resolve_channel_id_for_bot(token: str, target: str) -> str:
    """Map OpenClaw-style --target into a Discord channel ID for bot transport."""
    if target.startswith("channel:"):
        return target[len("channel:"):]
    if target.startswith("user:"):
        user_id = target[len("user:"):]
        cp = run([
            "curl", "-sS", "--fail-with-body", "-X", "POST",
            "-H", f"Authorization: Bot {token}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps({"recipient_id": user_id}),
            f"{DISCORD_API}/users/@me/channels",
        ])
        if cp.returncode != 0:
            raise RuntimeError(
                f"failed to open DM for user {user_id}: {(cp.stdout + cp.stderr).strip()[-2000:]}"
            )
        return json.loads(cp.stdout)["id"]
    if target.isdigit():
        return target
    raise ValueError(
        f"invalid --target for bot transport: {target!r}; expected channel:<id> or user:<id>"
    )


def find_latest_image_url_via_bot(channel_id: str) -> str | None:
    token = os.environ["DISCORD_BOT_TOKEN"]
    cp = run([
        "curl", "-sS", "--fail-with-body",
        "-H", f"Authorization: Bot {token}",
        f"{DISCORD_API}/channels/{channel_id}/messages?limit=20",
    ])
    if cp.returncode != 0:
        return None
    try:
        msgs = json.loads(cp.stdout)
    except Exception:
        return None
    for msg in msgs:
        for att in (msg.get("attachments") or []):
            filename = att.get("filename") or ""
            ctype = (att.get("content_type") or "").lower()
            url = att.get("url") or att.get("proxy_url")
            if not url:
                continue
            if ctype.startswith("image/") or is_image_filename(filename):
                return url
    return None


def find_latest_image_url_via_openclaw(target: str) -> str | None:
    cp = run([
        "openclaw", "message", "read",
        "--channel", "discord",
        "--target", target,
        "--limit", "20",
        "--json",
    ])
    if cp.returncode != 0:
        return None
    try:
        j = json.loads(cp.stdout)
    except Exception:
        return None
    msgs = (((j or {}).get("payload") or {}).get("messages") or [])
    for msg in msgs:
        for att in (msg.get("attachments") or []):
            filename = att.get("filename") or ""
            ctype = (att.get("content_type") or att.get("contentType") or "").lower()
            url = att.get("url") or att.get("proxy_url") or att.get("proxyUrl")
            if not url:
                continue
            if ctype.startswith("image/") or is_image_filename(filename):
                return url
    return None


def find_latest_image_url(transport: str, target: str) -> str | None:
    if transport == "bot":
        channel_id = resolve_channel_id_for_bot(os.environ["DISCORD_BOT_TOKEN"], target)
        return find_latest_image_url_via_bot(channel_id)
    if transport == "openclaw":
        return find_latest_image_url_via_openclaw(target)
    return None  # webhook path was rejected earlier


# ---------------------------------------------------------------------------
# Filesystem helpers (image extraction from provider output dir)
# ---------------------------------------------------------------------------

def snapshot_image_paths(root: str) -> set[str]:
    if not os.path.isdir(root):
        return set()
    found: set[str] = set()
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if is_image_filename(name):
                found.add(os.path.join(dirpath, name))
    return found


def newest_image_created_since(root: str, started_at: float, exclude: set[str]) -> str | None:
    if not os.path.isdir(root):
        return None
    best_path: str | None = None
    best_mtime: float = -1.0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if not is_image_filename(name):
                continue
            p = os.path.join(dirpath, name)
            if p in exclude:
                continue
            try:
                m = os.path.getmtime(p)
            except OSError:
                continue
            if m + 1 < started_at:
                continue
            if m > best_mtime:
                best_mtime = m
                best_path = p
    return best_path


# ---------------------------------------------------------------------------
# Senders (one per transport). Each returns (ok, error_text).
# ---------------------------------------------------------------------------

def send_via_webhook(out_path: str, message: str) -> tuple[bool, str]:
    url = os.environ["DISCORD_WEBHOOK_URL"]
    payload = json.dumps({"content": message})
    ctype = image_content_type(out_path)
    cp = run([
        "curl", "-sS", "--fail-with-body", "-X", "POST",
        "-F", f"payload_json={payload}",
        "-F", f"files[0]=@{out_path};type={ctype}",
        url,
    ])
    if cp.returncode == 0:
        return True, ""
    return False, (cp.stdout + "\n" + cp.stderr).strip()


def send_via_bot(out_path: str, target: str, message: str) -> tuple[bool, str]:
    token = os.environ["DISCORD_BOT_TOKEN"]
    try:
        channel_id = resolve_channel_id_for_bot(token, target)
    except Exception as e:
        return False, str(e)
    payload = json.dumps({"content": message})
    ctype = image_content_type(out_path)
    cp = run([
        "curl", "-sS", "--fail-with-body", "-X", "POST",
        "-H", f"Authorization: Bot {token}",
        "-F", f"payload_json={payload}",
        "-F", f"files[0]=@{out_path};type={ctype}",
        f"{DISCORD_API}/channels/{channel_id}/messages",
    ])
    if cp.returncode == 0:
        return True, ""
    return False, (cp.stdout + "\n" + cp.stderr).strip()


def send_via_openclaw(out_path: str, target: str, message: str) -> tuple[bool, str]:
    cp = run([
        "openclaw", "message", "send",
        "--channel", "discord",
        "--target", target,
        "--message", message,
        "--media", out_path,
    ])
    if cp.returncode == 0:
        return True, ""
    return False, (cp.stderr or "").strip()


def send_media(out_path: str, message: str, transport: str, target: str | None) -> tuple[bool, str]:
    if transport == "webhook":
        return send_via_webhook(out_path, message)
    if transport == "bot":
        return send_via_bot(out_path, target or "", message)
    if transport == "openclaw":
        return send_via_openclaw(out_path, target or "", message)
    return False, f"Unknown transport: {transport}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True, help="Output image path. The calling agent decides this; for openclaw transport, point to ~/.openclaw/media/tool-image-generation/<name>.png.")
    ap.add_argument("--target", default=None, help='Discord target, e.g. channel:<id> or user:<id>. Required for bot / openclaw transports; ignored for webhook.')
    ap.add_argument("--message", default="generated image")
    ap.add_argument("--size", default="1024x1024")
    ap.add_argument(
        "--transport",
        default="auto",
        choices=["auto", "webhook", "bot", "openclaw"],
        help="Upload transport. auto = webhook > bot > openclaw based on env.",
    )
    ap.add_argument(
        "--cd",
        default=os.environ.get("OPENCLAW_WORKSPACE")
        or os.path.expanduser("~/.openclaw/workspace"),
        help="Working directory passed to `codex exec --cd`. Defaults to $OPENCLAW_WORKSPACE, otherwise ~/.openclaw/workspace.",
    )
    ap.add_argument("-i", "--image", action="append", default=[], help="Local image path to use as reference (repeatable)")
    ap.add_argument("--image-url", action="append", default=[], help="Discord CDN image URL to download and use as reference (repeatable)")
    ap.add_argument("--use-latest-discord-image", action="store_true", help="Use the most recent image attachment in the target channel (bot or openclaw transport only)")
    args = ap.parse_args()

    transport = resolve_transport(args.transport)
    validate_transport_args(transport, args)

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        ref_images: list[str] = []
        for p in (args.image or []):
            if p:
                ref_images.append(os.path.abspath(os.path.expanduser(p)))

        for idx, url in enumerate(args.image_url or []):
            if not url:
                continue
            dl_path = os.path.join(td, f"ref-{idx}.img")
            try:
                download_url_to_file(url, dl_path)
            except Exception as e:
                sys.stderr.write(f"Failed to download image-url: {e}\n")
                return 6
            ref_images.append(dl_path)

        if args.use_latest_discord_image:
            url = find_latest_image_url(transport, args.target or "")
            if not url:
                sys.stderr.write("Could not find a recent image attachment in the target channel.\n")
                return 7
            dl_path = os.path.join(td, "ref-latest.img")
            try:
                download_url_to_file(url, dl_path)
            except Exception as e:
                sys.stderr.write(f"Failed to download latest Discord image: {e}\n")
                return 8
            ref_images.append(dl_path)

        mode_line = (
            "Transform or extend the attached reference image(s)."
            if ref_images
            else "Generate a new image."
        )

        gen_prompt = (
            f"$imagegen\n"
            f"{mode_line}\n"
            f"Size: {args.size}.\n"
            f"Instruction: {args.prompt}\n"
        )

        before = snapshot_image_paths(CODEX_IMAGES_DIR)
        started_at = time.time()

        cmd = [
            "codex", "exec",
            "--skip-git-repo-check",
            "--cd", args.cd,
        ]
        for p in ref_images:
            cmd.extend(["-i", p])
        # NOTE: with -i/--image attached, newer Codex CLI may treat the trailing
        # positional ambiguously unless we force end-of-options. Keep "--".
        cmd.extend(["--", gen_prompt])

        try:
            cp = run(cmd, timeout=EXEC_TIMEOUT)
        except subprocess.TimeoutExpired:
            sys.stderr.write(f"codex exec exceeded {EXEC_TIMEOUT}s; aborting.\n")
            return 9

        if cp.returncode != 0:
            sys.stderr.write("codex exec failed\n")
            sys.stderr.write((cp.stderr or "")[-4000:] + "\n")
            sys.stderr.write((cp.stdout or "")[-2000:] + "\n")
            return cp.returncode

        new_img = newest_image_created_since(CODEX_IMAGES_DIR, started_at, before)
        if not new_img:
            sys.stderr.write(
                "codex exec finished but no new image appeared under "
                f"{CODEX_IMAGES_DIR}. Is image_generation enabled and the host signed in?\n"
            )
            sys.stderr.write("codex stdout (tail):\n" + (cp.stdout or "")[-2000:] + "\n")
            return 3

        with open(new_img, "rb") as fsrc:
            img = fsrc.read()
        # Minimal sanity check: reject obviously wrong files (e.g. empty or HTML error pages).
        if len(img) < 64:
            sys.stderr.write(f"File at {new_img} is suspiciously small ({len(img)} bytes).\n")
            return 5
        with open(out_path, "wb") as fdst:
            fdst.write(img)

    ok, err = send_media(out_path, args.message, transport, args.target)

    if not ok:
        if "Failed to optimize image" in err:
            fallback_path = out_path + ".dat"
            try:
                shutil.copyfile(out_path, fallback_path)
            except Exception as e:
                sys.stderr.write("send failed (optimize image) and could not write fallback file\n")
                sys.stderr.write(str(e) + "\n")
                sys.stderr.write(err[-4000:] + "\n")
                return 4
            ext = os.path.splitext(out_path)[1] or ".png"
            note = f"(Discord image optimization failed; uploaded as a generic file. Rename back to {ext} after download to view.)"
            ok2, err2 = send_media(fallback_path, args.message + "\n" + note, transport, args.target)
            if not ok2:
                sys.stderr.write("send failed (fallback .dat)\n")
                sys.stderr.write(err2[-4000:] + "\n")
                return 4
        else:
            sys.stderr.write(f"send failed via transport={transport}\n")
            sys.stderr.write(err[-4000:] + "\n")
            return 4

    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
