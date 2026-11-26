"""Locate the external binaries this app shells out to.

A portable build cannot assume anything is on PATH: it gets unzipped into an
arbitrary folder and started with a bundled Python. So every tool is looked up
next to the app first (`bin/`), and only then on PATH.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]

# A windowed interpreter (`pythonw.exe`) has no console, so every child process
# Windows spawns would otherwise get a fresh console window — the black rectangle
# that flashed on start-up, on 生成, and on any ffmpeg call. `CREATE_NO_WINDOW`
# suppresses it for all of them; it is a no-op on POSIX.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def run(cmd, **kwargs) -> subprocess.CompletedProcess:
    """`subprocess.run` with the console window suppressed."""
    # `creationflags` must be OR-ed, not overwritten: callers that already pass
    # CREATE_NEW_PROCESS_GROUP (or anything else) would otherwise lose either
    # their flag or the no-window one.
    kwargs["creationflags"] = kwargs.get("creationflags", 0) | NO_WINDOW
    return subprocess.run(cmd, **kwargs)


def popen(cmd, **kwargs) -> subprocess.Popen:
    """`subprocess.Popen` with the console window suppressed."""
    kwargs["creationflags"] = kwargs.get("creationflags", 0) | NO_WINDOW
    return subprocess.Popen(cmd, **kwargs)


def _names(tool: str) -> list[str]:
    if sys.platform == "win32":
        return [f"{tool}.exe", tool]
    return [tool]


def find(tool: str) -> str | None:
    """Absolute path to `tool`, preferring a copy bundled with the app."""
    override = os.environ.get(f"UTALEARN_{tool.upper()}")
    if override and Path(override).exists():
        return str(Path(override))

    search = [APP_ROOT / "bin", APP_ROOT / "vendor" / "bin"]
    for folder in search:
        for name in _names(tool):
            candidate = folder / name
            if candidate.exists():
                return str(candidate)
    return shutil.which(tool)


def ffmpeg() -> str:
    return find("ffmpeg") or "ffmpeg"


def ffprobe() -> str:
    return find("ffprobe") or "ffprobe"


def probe_duration(path, timeout: float = 20.0) -> float:
    """Media duration in seconds, read from `ffmpeg -i`'s banner.

    The portable build used to ship a second 104 MB binary just to answer this
    one question. `ffmpeg -i <file>` prints `Duration: HH:MM:SS.xx` on stderr
    for every format it can demux, so ffprobe is now optional — present on a
    developer machine, absent from the package.
    """
    import re

    try:
        # `text=True` normally yields str, but a redirect/encoding mishap can
        # leave it None — the regex below must not be handed a non-string
        out = run(
            [ffmpeg(), "-hide_banner", "-i", str(path)],
            capture_output=True, text=True, errors="replace",
            timeout=timeout, check=False,
        ).stderr or ""
    except (OSError, subprocess.SubprocessError):
        return 0.0
    m = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", out)
    if not m:
        return 0.0
    hours, minutes, seconds = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return hours * 3600 + minutes * 60 + seconds
