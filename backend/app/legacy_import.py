"""One-time import of an older install's data (§5.5.3).

A user upgrading from v1.x unzips v2 next to the old folder. Rather than
telling them to drag `localdata/`, `models/` and `browsers/` around by hand,
the app scans the parent directory, says what it found, and copies or moves it.

Safety rules:
  * never overwrite a dataset that already exists locally (the user's newer
    edits win; a name clash is reported, not merged),
  * dataset files are migrated by SongRepo on first read, so a v1 schema is
    fine — nothing here rewrites JSON,
  * "复制" is the default; "移动" is offered because deleting the old folder
    afterwards is the user's call, not ours.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.paths import APP_ROOT, DATA_DIR

SKIP = {"_uploads", "_ui", "_cache", "_lyrics", "_diagnostics", ".jobs.json",
        "settings.json", "logs"}


def _is_dataset(folder: Path) -> bool:
    return (folder / "song_data.json").is_file()


def _packs_in(folder: Path) -> dict[str, int]:
    """Size of the extension packs a candidate install carries, in MB."""
    out: dict[str, int] = {}
    for name in ("models", "browsers"):
        d = folder / name
        if d.is_dir():
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            if size:
                out[name] = round(size / 1048576)
    return out


def candidates() -> list[dict]:
    """Sibling folders that look like an older install."""
    found = []
    parent = APP_ROOT.parent
    if not parent.is_dir():
        return found
    for entry in sorted(parent.iterdir()):
        if not entry.is_dir():
            continue
        # the app folder may be `<parent>/UtaLearnNext` or the older
        # `<parent>/UtaLearnNext-1.3.0/UtaLearnNext`
        roots = [entry]
        nested = entry / "UtaLearnNext"
        if nested.is_dir():
            roots.append(nested)
        for root in roots:
            if root.resolve() == APP_ROOT.resolve():
                continue
            data = root / "localdata"
            if not data.is_dir():
                continue
            songs = [d for d in data.iterdir() if d.is_dir() and _is_dataset(d)]
            if not songs:
                continue
            found.append({
                "path": str(root),
                "label": root.name,
                "songs": len(songs),
                "song_names": [d.name for d in songs][:12],
                "packs": _packs_in(root),
                "version": _guess_version(root),
            })
    return found


def _guess_version(root: Path) -> str:
    for rel in ("backend/app/version.py", "BUILD_INFO.json"):
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if rel.endswith(".json"):
            try:
                return str(json.loads(text).get("version") or "")
            except ValueError:
                continue
        for line in text.splitlines():
            if line.startswith("APP_VERSION"):
                return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def import_from(source: str, move: bool = False) -> dict:
    """Copy or move one candidate's data into this install."""
    src = Path(source).resolve()
    if not src.is_dir():
        raise FileNotFoundError(source)
    # only accept a folder that really holds data, so a typo cannot copy the
    # app onto itself
    if not (src / "localdata").is_dir():
        raise ValueError("这个目录里没有 localdata/")
    if src == APP_ROOT.resolve():
        raise ValueError("不能从当前目录导入")

    copied = skipped = 0
    for song_dir in (src / "localdata").iterdir():
        if not song_dir.is_dir() or song_dir.name in SKIP:
            skipped += 1
            continue
        if not _is_dataset(song_dir):
            skipped += 1
            continue
        dest = DATA_DIR / song_dir.name
        if dest.exists():
            skipped += 1
            continue
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if move:
            shutil.move(str(song_dir), str(dest))
        else:
            shutil.copytree(song_dir, dest)
        copied += 1

    packs: dict[str, str] = {}
    for name in ("models", "browsers"):
        origin = src / name
        if not origin.is_dir():
            continue
        dest = APP_ROOT / name
        if dest.exists() and any(dest.iterdir()):
            packs[name] = "已存在,跳过"
            continue
        if move:
            shutil.move(str(origin), str(dest))
        else:
            shutil.copytree(origin, dest, dirs_exist_ok=True)
        packs[name] = "已导入"

    # the old settings are worth keeping when this install has none yet
    settings_src = src / "localdata" / "settings.json"
    settings_dest = DATA_DIR / "settings.json"
    settings_note = ""
    if settings_src.is_file() and not settings_dest.exists():
        shutil.copy2(settings_src, settings_dest)
        settings_note = "已沿用旧设置的代理与显示偏好"

    return {"copied": copied, "skipped": skipped, "packs": packs,
            "settings": settings_note, "source": str(src)}
