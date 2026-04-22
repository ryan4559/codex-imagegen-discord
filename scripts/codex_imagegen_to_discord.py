#!/usr/bin/env python3
"""Generate an image via Codex CLI ($imagegen) and upload it to Discord via OpenClaw.

Codex CLI's built-in image generation tool saves PNGs to
  ~/.codex/generated_images/<session-id>/ig_*.png
and references the path in the conversation. It does NOT return raw bytes in
the final message. So this script:
  1. snapshots that directory before running codex,
  2. runs `codex exec "$imagegen ..."` (no --output-schema),
  3. picks the newest PNG that appeared after start time,
  4. uploads it to Discord via `openclaw message send`.

An earlier revision used `--output-schema` to force Codex to return
`{"png_base64": "..."}`. That fought the built-in imagegen tool (which writes
files, not text) and caused Codex to loop -- burning quota. Do not reintroduce
a schema here without redesigning the extraction path.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
DISCORD_CDN_HOSTS = {"cdn.discordapp.com", "media.discordapp.net"}
CODEX_IMAGES_DIR = os.path.expanduser("~/.codex/generated_images")
CODEX_EXEC_TIMEOUT = 600  # seconds; imagegen turns are slow, but not infinite


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


def download_url_to_file(url: str, out_path: str) -> None:
    pu = urllib.parse.urlparse(url)
    if pu.scheme not in ("https", "http"):
        raise ValueError(f"unsupported url scheme: {pu.scheme}")
    host = (pu.hostname or "").lower()
    if host and host not in DISCORD_CDN_HOSTS:
        raise ValueError(f"refusing to download non-Discord host: {host}")

    req = urllib.request.Request(url, headers={"User-Agent": "openclaw-codex-imagegen/2.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    with open(out_path, "wb") as f:
        f.write(data)


def find_latest_discord_image_url(target: str) -> str | None:
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


def snapshot_png_paths(root: str) -> set[str]:
    if not os.path.isdir(root):
        return set()
    found: set[str] = set()
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.lower().endswith(".png"):
                found.add(os.path.join(dirpath, name))
    return found


def newest_png_created_since(root: str, started_at: float, exclude: set[str]) -> str | None:
    if not os.path.isdir(root):
        return None
    best_path: str | None = None
    best_mtime: float = -1.0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if not name.lower().endswith(".png"):
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--target", required=True, help='Discord target, e.g. channel:... or user:...')
    ap.add_argument("--message", default="codex image")
    ap.add_argument("--size", default="1024x1024")
    ap.add_argument(
        "--cd",
        default=os.environ.get("OPENCLAW_WORKSPACE")
        or os.path.expanduser("~/.openclaw/workspace"),
        help="Working directory passed to `codex exec --cd`. Defaults to $OPENCLAW_WORKSPACE, otherwise ~/.openclaw/workspace.",
    )
    ap.add_argument("-i", "--image", action="append", default=[], help="Local image path to use as reference (repeatable)")
    ap.add_argument("--image-url", action="append", default=[], help="Discord CDN image URL to download and use as reference (repeatable)")
    ap.add_argument("--use-latest-discord-image", action="store_true", help="Use the most recent image attachment found in the target Discord channel")
    args = ap.parse_args()

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
            url = find_latest_discord_image_url(args.target)
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

        codex_prompt = (
            f"$imagegen\n"
            f"{mode_line}\n"
            f"Size: {args.size}.\n"
            f"Instruction: {args.prompt}\n"
        )

        before = snapshot_png_paths(CODEX_IMAGES_DIR)
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
        cmd.extend(["--", codex_prompt])

        try:
            cp = run(cmd, timeout=CODEX_EXEC_TIMEOUT)
        except subprocess.TimeoutExpired:
            sys.stderr.write(f"codex exec exceeded {CODEX_EXEC_TIMEOUT}s; aborting.\n")
            return 9

        if cp.returncode != 0:
            sys.stderr.write("codex exec failed\n")
            sys.stderr.write((cp.stderr or "")[-4000:] + "\n")
            sys.stderr.write((cp.stdout or "")[-2000:] + "\n")
            return cp.returncode

        new_png = newest_png_created_since(CODEX_IMAGES_DIR, started_at, before)
        if not new_png:
            sys.stderr.write(
                "codex exec finished but no new PNG appeared under "
                f"{CODEX_IMAGES_DIR}. Is image_generation enabled and the host signed in?\n"
            )
            sys.stderr.write("codex stdout (tail):\n" + (cp.stdout or "")[-2000:] + "\n")
            return 3

        with open(new_png, "rb") as fsrc:
            img = fsrc.read()
        if not img.startswith(b"\x89PNG\r\n\x1a\n"):
            sys.stderr.write(f"File at {new_png} is not a PNG.\n")
            return 5
        with open(out_path, "wb") as fdst:
            fdst.write(img)

    def send_media(path: str, note: str | None = None) -> subprocess.CompletedProcess:
        msg = args.message if note is None else (args.message + "\n" + note)
        return run([
            "openclaw", "message", "send",
            "--channel", "discord",
            "--target", args.target,
            "--message", msg,
            "--media", path,
        ])

    mp = send_media(out_path)

    if mp.returncode != 0:
        err = (mp.stderr or "")
        if "Failed to optimize image" in err:
            fallback_path = out_path + ".dat"
            try:
                with open(out_path, "rb") as fsrc, open(fallback_path, "wb") as fdst:
                    fdst.write(fsrc.read())
            except Exception as e:
                sys.stderr.write("openclaw message send failed (optimize image) and could not write fallback file\n")
                sys.stderr.write(str(e) + "\n")
                sys.stderr.write(err[-4000:] + "\n")
                return mp.returncode

            note = "(Discord PNG optimization failed; uploaded as a generic file. Rename back to .png after download to view.)"
            mp2 = send_media(fallback_path, note=note)
            if mp2.returncode != 0:
                sys.stderr.write("openclaw message send failed (fallback .dat)\n")
                sys.stderr.write((mp2.stderr or "")[-4000:] + "\n")
                return mp2.returncode
        else:
            sys.stderr.write("openclaw message send failed\n")
            sys.stderr.write(err[-4000:] + "\n")
            return mp.returncode

    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
