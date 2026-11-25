"""24-hour search cache for the private lyric endpoints.

QQ Music and Kugou are reverse-engineered APIs with no published quota; a user
who retypes the same query five times (because they are comparing versions)
should not cost five round-trips each. Results are cached per query + source
set for a day — long enough to matter, short enough that a corrected upload
does not sit behind a stale list.

Only the *hit list* is cached, never the parsed lyrics: the text and timings a
user actually builds from must always come from the source.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from app.paths import DATA_DIR

TTL = 24 * 3600
CACHE_FILE = DATA_DIR / "_cache" / "search.json"
_LOCK = threading.Lock()
_MAX_ENTRIES = 200


def _key(query: str, names: list[str] | None) -> str:
    # normalised: " 夜に駆ける " and "夜に駆ける" are the same search
    return f"{query.strip().lower()}|{','.join(sorted(names or []))}"


def _read() -> dict:
    try:
        raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write(data: dict) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, CACHE_FILE)
    except OSError:
        pass


def get(query: str, names: list[str] | None = None,
        now: float | None = None) -> tuple[list[dict], list[dict], dict[str, str]] | None:
    stamp = now or time.time()
    with _LOCK:
        entry = _read().get(_key(query, names))
    if not entry:
        return None
    if stamp - float(entry.get("at") or 0) > TTL:
        return None
    return (entry.get("results") or [], entry.get("errors") or [],
            entry.get("statuses") or {})


def put(query: str, names: list[str] | None, results: list[dict],
        errors: list[dict], statuses: dict[str, str],
        now: float | None = None) -> None:
    # an all-sources-failed response is not worth remembering: it would hide a
    # source that came back a minute later
    if not results and errors and len(errors) >= len(statuses or {1: 0}):
        return
    stamp = now or time.time()
    with _LOCK:
        data = _read()
        data[_key(query, names)] = {
            "at": stamp, "results": results, "errors": errors,
            "statuses": statuses,
        }
        if len(data) > _MAX_ENTRIES:
            oldest = sorted(data, key=lambda k: data[k].get("at", 0))
            for key in oldest[: len(data) - _MAX_ENTRIES]:
                data.pop(key, None)
        _write(data)


def clear() -> int:
    with _LOCK:
        data = _read()
        CACHE_FILE.unlink(missing_ok=True)
    return len(data)


def path() -> Path:
    return CACHE_FILE
