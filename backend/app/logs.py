"""Rolling file log, plus the diagnostic bundle users attach to bug reports.

A portable app has no `%PROGRAMDATA%\\logs` to fall back on and the console
window vanishes the moment the user closes it, so anything that goes wrong is
unreproducible unless it is written down. Two 2 MB files is enough to catch a
session's worth of failures and small enough to attach to a GitHub issue.

The bundle deliberately contains **no audio and no lyrics** — it is a support
artefact, not a backup — and paths are rewritten so a bug report never leaks
the user's account name.
"""
from __future__ import annotations

import logging
import platform
import re
import sys
import sysconfig
import zipfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app import packs, settings
from app.paths import APP_ROOT, DATA_DIR, EXPORT_DIR
from app.version import APP_NAME, APP_VERSION

LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "utalearn.log"
MAX_BYTES = 2 * 1024 * 1024
BACKUPS = 5

_USER_PATTERNS = (
    re.compile(r"([A-Za-z]:[\\/]Users[\\/])[^\\/\r\n\"']+", re.IGNORECASE),
    re.compile(r"(/home/)[^/\r\n\"']+"),
)


def scrub(text: str) -> str:
    """Replace the account name in paths with `<user>`."""
    for pattern in _USER_PATTERNS:
        text = pattern.sub(r"\1<user>", text)
    home = str(Path.home())
    if home:
        text = text.replace(home, "<user>")
    return text


def setup(level: int = logging.INFO) -> logging.Logger:
    """Attach the rolling file handler once; safe to call repeatedly."""
    logger = logging.getLogger("utalearn")
    if any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        return logger
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(LOG_FILE, maxBytes=MAX_BYTES,
                                      backupCount=BACKUPS, encoding="utf-8")
    except OSError:
        # a read-only app folder must not stop the server from starting
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def log() -> logging.Logger:
    return setup()


def recent_lines(limit: int = 400) -> list[str]:
    """The tail of the current log plus the previous file, scrubbed."""
    out: list[str] = []
    for path in (LOG_FILE.with_suffix(".log.1"), LOG_FILE):
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        out.extend(lines[-limit:])
    return [scrub(line) for line in out[-limit:]]


def environment() -> dict:
    """Everything a maintainer needs to reproduce a report — nothing personal."""
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "python": sys.version.split()[0],
        "executable": scrub(sys.executable),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "app_root": scrub(str(APP_ROOT)),
        "data_dir": scrub(str(DATA_DIR)),
        "export_dir": scrub(str(EXPORT_DIR)),
        "stdlib": scrub(sysconfig.get_paths().get("stdlib", "")),
        "packs": {
            "custom_lyrics": packs.custom_lyrics_installed(),
            "chromium": packs.chromium_installed(),
        },
        "settings": {
            k: v for k, v in settings.load().items()
            # never ship the install id or anything network-identifying
            if k not in ("install_id", "telemetry_last_day")
        },
    }


def build_bundle(dest: Path, extra: dict[str, str] | None = None) -> Path:
    """Write a diagnostic zip: environment, logs, optional text snippets."""
    import json

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("environment.json",
                   json.dumps(environment(), ensure_ascii=False, indent=2))
        z.writestr("log.txt", "\n".join(recent_lines()) + "\n")
        z.writestr("README.txt",
                   "Uta Learn Next 诊断信息。\n"
                   "包含版本、系统、路径、扩展包状态与最近的日志。\n"
                   "不包含音频、歌词或任何个人信息（路径里的用户名已替换为 <user>）。\n")
        for name, text in (extra or {}).items():
            z.writestr(name, scrub(text))
    return dest
