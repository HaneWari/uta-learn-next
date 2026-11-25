"""Where data lives and how the folder layout is resolved.

Everything is resolved against the *application folder*, never the current
working directory: a portable build gets unzipped anywhere and started from
anywhere, and `../localdata` relative to CWD silently pointed at the wrong
place (or at nothing) as soon as the launcher's working directory changed.

Resolution order for a writable directory: env override → folder next to the
app → per-user directory (when the app folder is read-only, e.g. Program Files).
"""
from __future__ import annotations

import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent.parent

NO_CACHE = {"Cache-Control": "no-store, max-age=0"}


def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _user_dir(name: str) -> Path:
    """Per-user fallback for when the app folder itself is read-only."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "UtaLearnNext" / name


def resolve_dir(env_name: str, portable: Path, fallback_name: str) -> Path:
    """env override → folder next to the app → per-user directory."""
    raw = os.environ.get(env_name)
    if raw:
        p = Path(raw).expanduser()
        return (p if p.is_absolute() else APP_ROOT / p).resolve()
    if _is_writable(portable):
        return portable.resolve()
    return _user_dir(fallback_name)


DATA_DIR = resolve_dir("DATA_DIR", APP_ROOT / "localdata", "localdata")
UPLOAD_DIR = DATA_DIR / "_uploads"
UI_DIR = DATA_DIR / "_ui"
EXPORT_DIR = resolve_dir("EXPORT_DIR", APP_ROOT / "exports", "exports")
DIST_DIR = APP_ROOT / "frontend" / "dist"

DEFAULT_SONG = os.environ.get("DEFAULT_SONG", "braveheart")
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".mp4"}
MAX_UPLOAD = 200 * 1024 * 1024

# Where the export's headless browser should reach this server. Override with
# UTALEARN_BASE_URL when running behind a different host/port.
BASE_URL = os.environ.get("UTALEARN_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
