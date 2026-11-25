"""Dataset folder helpers: naming, lookup, audio probing and staging uploads.

A dataset is one folder under `DATA_DIR` holding `song_data.json` and,
optionally, `audio.mp3`. These functions are the only place that knows that
layout; route modules should call them instead of joining paths by hand.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

from fastapi import HTTPException

from app import fallback, repo
from app.builder import slugify
from app.paths import DATA_DIR, DEFAULT_SONG, UPLOAD_DIR
from app.version import APP_VERSION

# Browsers play these straight from an <audio> element. Anything else (wma, and
# some aac files) is transcoded at import time — a dataset whose audio the
# stage cannot decode is worse than a slightly larger file.
BROWSER_AUDIO = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".mp4": "audio/mp4",
}
NEEDS_TRANSCODE = {".wma"}
STAGE_AUDIO_NAME = "audio"          # + the real extension


def dataset(name: str | None) -> Path:
    if name:
        # `_`-prefixed folders are internal (_uploads, _ui) and must never be
        # reachable as a song, same rule list_datasets uses.
        if "/" in name or "\\" in name or name.startswith(".") or name.startswith("_"):
            raise HTTPException(status_code=400, detail="bad song name")
        candidate = DATA_DIR / name
        if not candidate.is_dir():
            # Generating the same song twice appends "-2", and deleting the older
            # one leaves stale links behind. Point at the survivor instead of a
            # bare "not found".
            base = re.sub(r"-\d+$", "", name)
            near = [p.name for p in DATA_DIR.glob(f"{base}*") if p.is_dir()] \
                if DATA_DIR.is_dir() else []
            hint = f"，可用的是：{'、'.join(near[:3])}" if near else ""
            raise HTTPException(status_code=404, detail=f"unknown song: {name}{hint}")
        return candidate
    nested = DATA_DIR / DEFAULT_SONG
    if nested.is_dir() and (nested / "song_data.json").exists():
        return nested
    return DATA_DIR


_AUDIO_DUR: dict[tuple[str, float, int], float] = {}


def audio_duration(path: Path) -> float:
    """Actual playable length of a dataset's audio file (0 when unreadable).

    `meta.duration_seconds` describes the *lyric timeline*, which is regularly
    shorter than the user's own file (a trimmed intro, a different edit), so the
    song list has to ask the audio itself or it advertises the wrong length.
    """
    try:
        st = path.stat()
    except OSError:
        return 0.0
    key = (str(path), st.st_mtime, st.st_size)
    cached = _AUDIO_DUR.get(key)
    if cached is None:
        if len(_AUDIO_DUR) > 64:
            _AUDIO_DUR.clear()
        cached = float(fallback.probe_duration(path) or 0.0)
        _AUDIO_DUR[key] = cached
    return cached


def prune_uploads(max_age_hours: float = 24.0) -> int:
    """Drop staging uploads that were never turned into a dataset.

    Every build copies the audio into its dataset, so a file left in _uploads is
    only useful while the user is still in the middle of configuring that song.
    Without this the folder grows without bound.
    """
    if not UPLOAD_DIR.is_dir():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for f in UPLOAD_DIR.iterdir():
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def list_datasets() -> list[dict]:
    if not DATA_DIR.is_dir():
        return []
    out = []
    for entry in sorted(DATA_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        data = entry / "song_data.json"
        if not data.exists():
            continue
        meta = repo.read_meta(data)
        audio = find_audio(entry)
        has_audio = audio is not None
        out.append({
            "name": entry.name,
            "title": meta.get("title") or entry.name,
            "artist": meta.get("artist") or "",
            "duration": (audio_duration(audio) if audio else 0)
                        or meta.get("duration_seconds") or 0,
            "has_audio": has_audio,
            "source": meta.get("source") or "",
        })
    return out


def free_name(base: str) -> str:
    name = slugify(base) or "song"
    candidate, i = name, 2
    while (DATA_DIR / candidate).exists():
        candidate = f"{name}-{i}"
        i += 1
    return candidate


def save_dataset(name: str, song: dict, audio: Path | None) -> Path:
    out = DATA_DIR / name
    out.mkdir(parents=True, exist_ok=True)
    # Record whether an audio file is actually present: the stage must not
    # request /api/audio for a lyrics-only dataset, and duration_seconds is the
    # length of the lyric timeline, not proof of a file.
    has_audio = audio is not None and audio.exists()
    target: Path | None = None
    if has_audio:
        source = audio
        ext = audio.suffix.lower()
        if ext in NEEDS_TRANSCODE:
            # the stage is a browser: wma simply does not play there
            converted = out / f"{STAGE_AUDIO_NAME}.m4a"
            _transcode(audio, converted)
            source, ext = converted, ".m4a"
        elif ext not in BROWSER_AUDIO:
            ext = ".mp3"
        target = out / f"{STAGE_AUDIO_NAME}{ext}"
        if source != target:
            shutil.copyfile(source, target)
        if source != audio:
            source.unlink(missing_ok=True)
    meta = song.setdefault("meta", {})
    meta["has_audio"] = bool(has_audio)
    # the file name is recorded rather than assumed: a dataset keeps its own
    # format, and `audio.mp3` no longer describes a flac or an m4a
    if target is not None:
        meta["audio_file"] = target.name
    else:
        meta.pop("audio_file", None)
    repo.write_new(out / "song_data.json", song, APP_VERSION)
    return out


def _transcode(src: Path, dst: Path) -> None:
    from app import binaries

    subprocess.run(
        [binaries.ffmpeg(), "-y", "-v", "error", "-i", str(src),
         "-vn", "-c:a", "aac", "-b:a", "192k", str(dst)],
        check=True, capture_output=True,
    )


def find_audio(folder: Path) -> Path | None:
    """The dataset's audio file, whatever format it was imported in.

    Older datasets name it `audio.mp3` even when the bytes are a flac; the
    directory scan covers both, so no migration is needed.
    """
    for ext in BROWSER_AUDIO:
        candidate = folder / f"{STAGE_AUDIO_NAME}{ext}"
        if candidate.exists():
            return candidate
    legacy = folder / "audio.mp3"
    return legacy if legacy.exists() else None


def audio_mime(path: Path) -> str:
    return BROWSER_AUDIO.get(path.suffix.lower(), "application/octet-stream")


def upload_path(upload_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", upload_id or ""):
        raise HTTPException(status_code=400, detail="bad upload id")
    for p in UPLOAD_DIR.glob(f"{upload_id}.*"):
        return p
    raise HTTPException(status_code=404, detail="上传的音频已过期，请重新上传")


def meta_flag(name: str, key: str) -> bool:
    """Read a boolean meta flag off a dataset without trusting the caller."""
    return bool(repo.read_meta(dataset(name) / "song_data.json").get(key))


def mmss(raw) -> float:
    """Parse a "m:ss" (or plain seconds) crop point; anything else is 0."""
    if raw is None or raw == "":
        return 0.0
    if isinstance(raw, (int, float)):
        return max(0.0, float(raw))
    s = str(raw).strip()
    if ":" in s:
        try:
            m, sec = s.split(":", 1)
            return max(0.0, int(m) * 60 + float(sec))
        except ValueError:
            return 0.0
    try:
        return max(0.0, float(s))
    except ValueError:
        return 0.0
