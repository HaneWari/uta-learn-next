"""Locate the external binaries this app shells out to.

A portable build cannot assume anything is on PATH: it gets unzipped into an
arbitrary folder and started with a bundled Python. So every tool is looked up
next to the app first (`bin/`), and only then on PATH.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]


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
