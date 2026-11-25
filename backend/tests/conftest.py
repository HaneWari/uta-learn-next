"""Test bootstrap.

`main.py` resolves DATA_DIR / EXPORT_DIR at *import* time, so the environment
has to be redirected before any test module imports the app. Conftest is
imported ahead of the test modules, so the module-level block below is the
one reliable hook — a fixture would run too late.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

BASE = Path(tempfile.mkdtemp(prefix="uta-tests-"))

os.environ["DATA_DIR"] = str(BASE / "localdata")
os.environ["EXPORT_DIR"] = str(BASE / "exports")
# no token checks, no telemetry, deterministic default song
os.environ["UTALEARN_DEV"] = "1"
os.environ["UTALEARN_TELEMETRY"] = "0"
os.environ["DEFAULT_SONG"] = "song"


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(BASE, ignore_errors=True)


@pytest.fixture
def data_dir() -> Path:
    """A fresh, empty data directory for one test."""
    d = BASE / "localdata"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_song(name: str, data: dict, data_dir: Path | None = None) -> Path:
    """Create `<data>/<name>/song_data.json` and return its path."""
    root = (data_dir or Path(os.environ["DATA_DIR"])) / name
    root.mkdir(parents=True, exist_ok=True)
    path = root / "song_data.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def make_song(data_dir):
    """Factory: `make_song("foo", segments=[...])` → song_data.json path."""
    def _make(name: str = "song", **meta):
        data = {
            "meta": {"title": name, "artist": "", "duration_seconds": 10.0, **meta},
            "segments": [
                {"id": 0, "start": 0.0, "end": 2.0, "text": "テスト",
                 "romaji": "tesuto", "words": []},
            ],
        }
        return write_song(name, data, data_dir)
    return _make
