"""Extension packs: version-independent zips fetched from the latest release.

A pack is a plain zip whose members live under one top-level folder next to the
app (`models/`, `browsers/`). Both packs are built once and reused by every app
version, so the installer never has to know about versions at all:

    UtaLearnNext-custom-lyrics.zip   models/whisper-small + models/translate-ja-zh
    UtaLearnNext-chromium.zip        browsers/chromium-*

Downloads stream to a temp file instead of a 500 MB `BytesIO`: an in-memory
buffer would double the peak RSS right when the app is also running whisper.
"""
from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

import httpx

from app.paths import APP_ROOT

GITHUB_REPO = "HaneWari/uta-learn-next"
CUSTOM_ASSET = "UtaLearnNext-custom-lyrics.zip"
CHROMIUM_ASSET = "UtaLearnNext-chromium.zip"

WHISPER_NAME = "whisper-small"
TRANSLATE_NAME = "translate-ja-zh"


def latest_url(asset: str) -> str:
    """Stable download URL of an asset on the newest release.

    ``releases/latest/download/<asset>`` redirects to the newest release's
    asset without touching the API, so it is immune to the anonymous GitHub
    API rate limit that would otherwise 403 the install on a busy day.
    """
    return f"https://github.com/{GITHUB_REPO}/releases/latest/download/{asset}"


def download(asset: str, dest: Path, progress=None, label: str = "") -> Path:
    """Stream one release asset to `dest` (10%→80% of the job's progress)."""
    say = progress or (lambda _p, _m: None)
    say(0.10, f"下载{label or asset}…")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    with httpx.Client(timeout=None, follow_redirects=True) as client:
        with client.stream("GET", latest_url(asset)) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            got = 0
            with part.open("wb") as fh:
                for chunk in r.iter_bytes(1 << 20):
                    fh.write(chunk)
                    got += len(chunk)
                    if total:
                        say(0.10 + 0.70 * got / total,
                            f"下载{label or asset}… {got // 1048576}MB")
    os.replace(part, dest)
    return dest


def unpack(zip_path: Path, top: str, dest_root: Path, progress=None) -> int:
    """Extract only the `top/` subtree of a pack into `dest_root`.

    Members that would escape `dest_root` are skipped outright — a pack is
    downloaded content, and `../../` in a zip entry must never be honoured.
    Older packs wrapped everything in `UtaLearnNext/`, which is tolerated by
    stripping that one prefix before the `top/` check.
    """
    say = progress or (lambda _p, _m: None)
    say(0.85, f"解压到 {top}/ …")
    root = dest_root.resolve()
    written = 0
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            rel = member[len("UtaLearnNext/"):] \
                if member.startswith("UtaLearnNext/") else member
            if not rel.startswith(f"{top}/"):
                continue
            target = (dest_root / rel).resolve()
            if not target.is_relative_to(root):
                continue
            if member.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            written += 1
    return written


def install_asset(asset: str, top: str, dest_root: Path | None = None,
                  progress=None, label: str = "") -> Path:
    """Download + unpack a pack, cleaning the temp zip up afterwards."""
    root = dest_root or APP_ROOT
    cache = root / "_downloads"
    zip_path = cache / asset
    download(asset, zip_path, progress, label)
    try:
        unpack(zip_path, top, root, progress)
    finally:
        zip_path.unlink(missing_ok=True)
        try:
            cache.rmdir()
        except OSError:
            pass
    return root / top


# --------------------------------------------------------------------------- #
# custom-lyrics pack: whisper STT + ja-zh translation
# --------------------------------------------------------------------------- #
def whisper_dir(root: Path | None = None) -> Path:
    return (root or APP_ROOT) / "models" / WHISPER_NAME


def translate_dir(root: Path | None = None) -> Path:
    return (root or APP_ROOT) / "models" / TRANSLATE_NAME


def whisper_installed(root: Path | None = None) -> bool:
    return (whisper_dir(root) / "model.bin").exists()


def translate_installed(root: Path | None = None) -> bool:
    return (translate_dir(root) / "model.bin").exists()


def custom_lyrics_installed(root: Path | None = None) -> bool:
    """The pack is only 'installed' when *both* models are in place — a
    whisper-only folder would silently lose the 中文翻译 option."""
    return whisper_installed(root) and translate_installed(root)


def install_custom_lyrics(progress=None) -> Path:
    root = install_asset(CUSTOM_ASSET, "models", progress=progress,
                         label="自定义歌词扩展包（约 265MB）")
    if not whisper_installed(root):
        raise RuntimeError("解压后未找到 models/whisper-small/model.bin")
    if not translate_installed(root):
        raise RuntimeError("解压后未找到 models/translate-ja-zh/model.bin")
    return root / "models"


# --------------------------------------------------------------------------- #
# chromium pack: a browser binary for the video export
# --------------------------------------------------------------------------- #
def browsers_dir(root: Path | None = None) -> Path:
    raw = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    return Path(raw) if raw else (root or APP_ROOT) / "browsers"


def chromium_installed(root: Path | None = None) -> bool:
    d = browsers_dir(root)
    return d.is_dir() and any(d.glob("chromium-*"))


def install_chromium(progress=None) -> Path:
    root = install_asset(CHROMIUM_ASSET, "browsers", progress=progress,
                         label="Chromium 扩展包（约 209MB）")
    if not chromium_installed(root):
        raise RuntimeError("解压后未找到 browsers/chromium-* 目录")
    return browsers_dir(root)
