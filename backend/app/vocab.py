"""Personal word book (`localdata/_vocab.json`).

One file rather than one per song: the point is to review across songs, and a
per-song layout would mean scanning every dataset folder to render the book.

Records are keyed by `song/id` so re-adding the same word from the same line
updates the note instead of duplicating it, and the same surface can be saved
twice from two different songs (it really is two encounters).
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from app.paths import DATA_DIR

VOCAB_FILE = DATA_DIR / "_vocab.json"
_LOCK = threading.Lock()


def _read() -> list[dict]:
    try:
        raw = json.loads(VOCAB_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return raw if isinstance(raw, list) else []


def _write(items: list[dict]) -> None:
    VOCAB_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = VOCAB_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, VOCAB_FILE)


def _key(item: dict) -> str:
    return f"{item.get('song', '')}/{item.get('segment_id', '')}/{item.get('text', '')}"


def list_all(song: str | None = None) -> list[dict]:
    items = _read()
    if song:
        items = [i for i in items if i.get("song") == song]
    # newest first: a just-saved word should be at the top of the list
    return sorted(items, key=lambda i: i.get("added_at", 0), reverse=True)


def add(item: dict) -> dict:
    """Insert or refresh one entry; returns the stored record."""
    record = {
        "song": item.get("song", ""),
        "song_title": item.get("song_title", ""),
        "segment_id": item.get("segment_id"),
        "text": (item.get("text") or "").strip(),
        "kana": item.get("kana") or "",
        "romaji": item.get("romaji") or "",
        "pos": item.get("pos") or "",
        "jlpt": item.get("jlpt") or "",
        "zh": item.get("zh") or "",
        "line": item.get("line") or "",
        "at": float(item.get("at") or 0),
        "added_at": time.time(),
    }
    if not record["text"] or not record["song"]:
        raise ValueError("缺少单词或歌名")
    with _LOCK:
        items = _read()
        key = _key(record)
        existing = next((i for i in items if _key(i) == key), None)
        if existing is not None:
            # keep the original "learned at" time, refresh the details
            record["added_at"] = existing.get("added_at", record["added_at"])
            items[items.index(existing)] = record
        else:
            items.append(record)
        _write(items)
    return record


def remove(song: str, segment_id: int, text: str) -> bool:
    target = {"song": song, "segment_id": segment_id, "text": text}
    with _LOCK:
        items = _read()
        key = _key(target)
        kept = [i for i in items if _key(i) != key]
        if len(kept) == len(items):
            return False
        _write(kept)
    return True


def clear(song: str | None = None) -> int:
    with _LOCK:
        items = _read()
        kept = [i for i in items if song and i.get("song") != song]
        removed = len(items) - len(kept)
        _write(kept)
    return removed


def count_by_song() -> dict[str, int]:
    out: dict[str, int] = {}
    for item in _read():
        song = item.get("song", "")
        out[song] = out.get(song, 0) + 1
    return out


def path() -> Path:
    return VOCAB_FILE
