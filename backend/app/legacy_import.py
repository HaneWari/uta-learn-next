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
import os
import re
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


def _scan_roots(entry: Path, deep: bool = True) -> list[Path]:
    """Every place inside one folder that may hold an install.

    Users unzip a version pack in all sorts of shapes:

        <dir>/UtaLearnNext/                 (v2's own layout)
        <dir>/UtaLearnNext-1.3.0/UtaLearnNext/
        <dir>/UtaLearnNext/localdata/       (data next to desktop.py)
        <dir>/localdata/                    (unzipped without the wrapper)
        <dir>/UtaLearnNext (1)/             (Windows renamed a duplicate)

    Earlier this only looked one level down and only for a literal
    `UtaLearnNext`, so a renamed folder or a pack whose root was the version
    directory silently produced zero candidates.
    """
    roots = [entry]
    if not deep:
        # Outer directories are only inspected for folders that are *named*
        # like the app. Recursing into every folder of a drive (or of a temp
        # tree) would drag in unrelated copies and slow the scan down.
        if not entry.name.lower().startswith(("utalearn", "uta learn")):
            return roots
    try:
        children = [p for p in entry.iterdir() if p.is_dir()]
    except OSError:
        children = []
    for child in children:
        name = child.name.lower()
        # a nested app folder, or a version directory; `(1)` suffixes come from
        # extracting a second copy into the same parent
        if name.startswith("utalearn") or name.startswith("uta learn") \
                or (child / "localdata").is_dir():
            roots.append(child)
    # and the app folder inside a version directory
    for child in list(roots):
        for grand in child.glob("*"):
            if grand.is_dir() and grand.name.lower().startswith(("utalearn", "uta learn")):
                roots.append(grand)
    return roots


def _candidate(root: Path, origin: Path) -> dict | None:
    data = root / "localdata"
    if not data.is_dir():
        return None
    try:
        dirs = [d for d in data.iterdir() if d.is_dir()]
    except OSError:
        return None
    songs = [d for d in dirs if _is_dataset(d)]
    if not songs:
        return None
    # Nested installs are almost always named `UtaLearnNext`, so the bare
    # folder name made the list read "UtaLearnNext ×4". The wrapper folder
    # (`UtaLearnNext-1.3.0`, `UtaLearnNext (1)`) is what tells them apart.
    label = root.name
    if root != origin:
        label = f"{origin.name} / {root.name}"
    return {
        "path": str(root),
        "label": label,
        "songs": len(songs),
        "song_names": [d.name for d in songs][:12],
        "packs": _packs_in(root),
        "version": _guess_version(root),
    }


def candidates() -> list[dict]:
    """Folders that look like an older install, near this one.

    The search runs over the app's parent directory (the usual case: the user
    unzips v2 next to v1.x) and, when that yields nothing, over the parent's
    parent. Both the app folder itself and any wrapper/version folder inside
    are considered, so renamed copies and nested packs are still found.
    """
    found: list[dict] = []
    seen: set[Path] = set()
    here = APP_ROOT.resolve()
    bases = [APP_ROOT.parent, APP_ROOT.parent.parent]
    # A portable install often lives somewhere deep (`E:\agent-space\…`) while
    # the old one was unzipped straight onto another drive's root
    # (`D:\UtaLearnNext-1.3.0`). Listing a drive's top level is cheap, so every
    # fixed drive gets the same shallow look — otherwise the feature silently
    # found nothing for anyone whose old copy lived on a different disk.
    drives = _fixed_drives()
    bases.extend(drives)
    for base in bases:
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if not entry.is_dir():
                continue
            # at a drive root, only folders that are named like the app: walking
            # one level into every folder of a whole drive would take seconds
            if base in drives and not entry.name.lower().startswith(
                    ("utalearn", "uta learn")):
                continue
            deep = base == APP_ROOT.parent
            for root in _scan_roots(entry, deep=deep):
                try:
                    resolved = root.resolve()
                except OSError:
                    continue
                if resolved == here or resolved in seen:
                    continue
                item = _candidate(root, entry)
                if not item:
                    continue
                seen.add(resolved)
                found.append(item)
        # keep going: the drive root may hold an older copy even after a parent
        # folder produced something (e.g. a half-deleted duplicate)
    return found


def _fixed_drives() -> list[Path]:
    """Top-level folders of every local fixed disk (Windows) or `/` + $HOME."""
    if os.name != "nt":
        return [Path("/"), Path.home()]
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        mask = kernel32.GetLogicalDrives()
        out: list[Path] = []
        for i in range(26):
            if not mask & (1 << i):
                continue
            root = Path(f"{chr(65 + i)}:\\")
            # DRIVE_FIXED = 3: skip USB sticks and optical drives, whose top
            # level can block for seconds when the media is absent
            if kernel32.GetDriveTypeW(str(root)) != 3:
                continue
            out.append(root)
        return out
    except Exception:  # noqa: BLE001
        return [Path(APP_ROOT.resolve().anchor)]


def _guess_version(root: Path) -> str:
    """Version of a candidate install, or "" when it cannot be known.

    v2 builds carry `BUILD_INFO.json` and a `backend/app/version.py`; the v1.2 /
    v1.3 packs shipped neither (their version only existed in the folder name
    the user unzipped to). Reading the folder name is therefore a required
    fallback, not a nice-to-have — without it every v1 entry showed no version.
    """
    for rel in ("BUILD_INFO.json", "backend/app/version.py"):
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if rel.endswith(".json"):
            try:
                found = str(json.loads(text).get("version") or "")
            except ValueError:
                found = ""
            if found:
                return _clean(found)
            continue
        for line in text.splitlines():
            if line.startswith("APP_VERSION"):
                return _clean(line.split("=", 1)[1].strip().strip('"\''))
    # the wrapper folder, then the app folder itself
    for name in (root.parent.name, root.name):
        m = re.search(r"\bv?(\d+\.\d+(?:\.\d+)?)\b", name)
        if m:
            return m.group(1)
    return ""


def _clean(value: str) -> str:
    return re.sub(r"[^0-9.]", "", value).strip(".")


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
