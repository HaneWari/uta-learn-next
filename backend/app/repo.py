"""The single write path for a dataset's `song_data.json`.
Every stage edit (cards, lyric overrides, offset, visibility) funnels through
`update()`; nothing else may write the file. That buys three properties the app
needed and did not have:
  * **no lost updates** — the read-modify-write cycle holds a per-file lock, and
    `expected_revision` turns a stale editor into a visible 409 instead of a
    silent overwrite;
  * **no truncated files** — writes go to `song_data.json.tmp`, are fsynced and
    then `os.replace`d, with the previous version kept as `.bak`;
  * **forward-only schema** — old files are migrated in memory (never rewritten
    on read), and a file written by a newer app is refused rather than
    downgraded.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
from collections.abc import Callable
from pathlib import Path

SCHEMA_VERSION = 2
FILENAME = "song_data.json"


class RevisionConflict(Exception):
    """The caller edited a stale copy: someone else saved first."""

    def __init__(self, current: int) -> None:
        super().__init__(f"revision {current}")
        self.current = current


class SchemaTooNew(Exception):
    """The file was written by a newer app; never rewrite it."""

    def __init__(self, found: int) -> None:
        super().__init__(f"schema {found}")
        self.found = found


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    key = str(path)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _LOCKS[key] = threading.RLock()
        return lock


def migrate(data: dict) -> dict:
    """Return `data` upgraded to `SCHEMA_VERSION` (a new dict when changed)."""
    try:
        version = int(data.get("schema_version") or 1)
    except (TypeError, ValueError):
        version = 1
    if version > SCHEMA_VERSION:
        raise SchemaTooNew(version)
    if version < 2:
        data = _v1_to_v2(data)
    return data


def _v1_to_v2(data: dict) -> dict:
    """v1 → v2: revision tracking for optimistic concurrency."""
    meta = data.get("meta")
    if not isinstance(meta, dict):
        meta = data["meta"] = {}
    meta.setdefault("revision", 0)
    out = {"schema_version": 2}
    out.update(data)
    return out


def _read_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read(path: Path) -> dict:
    """Load + migrate a dataset. Falls back to `.bak` if the main file is broken."""
    try:
        data = _read_file(path)
    except json.JSONDecodeError:
        backup = path.with_name(path.name + ".bak")
        if not backup.exists():
            raise
        print(f"[uta] {path.name} 损坏，已回退到备份 {backup.name}")
        data = _read_file(backup)
    return migrate(data)


def read_meta(path: Path) -> dict:
    """Best-effort `meta` for listings: never raises, never migrates."""
    try:
        meta = _read_file(path).get("meta")
        return meta if isinstance(meta, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _atomic_write(path: Path, data: dict) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_name(path.name + ".tmp")
    if path.exists():
        shutil.copyfile(path, path.with_name(path.name + ".bak"))
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def write_new(path: Path, data: dict, app_version: str = "") -> dict:
    """Create a fresh dataset (build pipeline). Locks, stamps, writes once."""
    with _lock_for(path):
        meta = data.setdefault("meta", {})
        meta.setdefault("revision", 0)
        if app_version:
            meta["app_version"] = app_version
        out = {"schema_version": SCHEMA_VERSION}
        out.update(data)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, out)
        return out


def update(path: Path, fn: Callable[[dict], object],
           expected_revision: int | None = None,
           app_version: str = "") -> dict:
    """Read-modify-write one dataset under a lock, atomically.
    `fn` mutates the dict in place (return value ignored) or returns a new dict.
    Raises `RevisionConflict` before touching the file when the caller is stale.
    """
    with _lock_for(path):
        data = read(path)
        meta = data.setdefault("meta", {})
        current = int(meta.get("revision") or 0)
        if expected_revision is not None and expected_revision != current:
            raise RevisionConflict(current)
        out = fn(data) or data
        out.setdefault("schema_version", SCHEMA_VERSION)
        meta = out.setdefault("meta", {})
        meta["revision"] = current + 1
        if app_version:
            meta["app_version"] = app_version
        _atomic_write(path, out)
        return out
