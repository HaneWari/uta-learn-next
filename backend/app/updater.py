"""Update check, patch download and staged swap-in.

Two kinds of update, decided by `runtime_id`:

* same runtime → the patch zip (about 5 MB: `backend/` + `frontend/dist/`)
  replaces the app layer on the next start;
* different runtime → the full zip, unpacked beside the current folder; the
  user starts it and keeps the old one until they are happy.

Nothing here installs silently. A user can be mid-render or mid-transcription,
and swapping files under a running job would be worse than being one version
behind for a day.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path

import httpx

from app.paths import APP_ROOT
from app.sources import resolve_proxy
from app.version import APP_VERSION

REPO = "HaneWari/uta-learn-next"
MANIFEST_ASSET = "update.json"
STAGING = APP_ROOT / "_update"
BACKUP = APP_ROOT / "app.prev"
# `state.json` lives inside STAGING; computed at call time so a test (or a
# relocated data dir) that swaps STAGING is honoured instead of writing to the
# path the module saw at import


def _state_file() -> Path:
    return STAGING / "state.json"


class NoManifest(RuntimeError):
    """The latest release predates the updater, so it has no `update.json`."""


def local_runtime_id() -> str:
    """The `runtime_id` this build was made with (from BUILD_INFO.json)."""
    try:
        info = json.loads((APP_ROOT / "BUILD_INFO.json").read_text(encoding="utf-8"))
        return str(info.get("runtime_id") or "")
    except (OSError, ValueError):
        return ""


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for chunk in str(value).split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(candidate: str, current: str = APP_VERSION) -> bool:
    return _version_tuple(candidate) > _version_tuple(current)


def fetch_manifest(timeout: float = 10.0) -> dict:
    """The newest release's `update.json` (the only file this reads).

    A release published before the updater existed has no manifest. That is
    the normal state of the world until the first v2 release ships, so it is
    reported as "no update information" rather than an HTTP error the UI would
    show verbatim.
    """
    url = f"https://github.com/{REPO}/releases/latest/download/{MANIFEST_ASSET}"
    with httpx.Client(proxy=resolve_proxy(), timeout=timeout,
                      follow_redirects=True) as client:
        r = client.get(url)
        if r.status_code == 404:
            raise NoManifest(
                "当前发行版没有更新清单(这个版本早于自动更新)")
        r.raise_for_status()
        return r.json()


def decide(manifest: dict, runtime_id: str | None = None) -> dict:
    """Compare a manifest with this build and say what an update would cost."""
    latest = str(manifest.get("version") or "")
    local_runtime = runtime_id if runtime_id is not None else local_runtime_id()
    remote_runtime = str(manifest.get("runtime_id") or "")
    available = bool(latest) and is_newer(latest)
    same_runtime = bool(local_runtime) and local_runtime == remote_runtime
    patch = manifest.get("patch") or {}
    patch = {**patch, "version": latest}
    full = {**(manifest.get("full") or {}), "version": latest}
    return {
        "current": APP_VERSION,
        "latest": latest,
        "available": available,
        "kind": ("patch" if same_runtime else "full") if available else None,
        "runtime_changed": available and not same_runtime,
        "notes": manifest.get("notes") or "",
        "published_at": manifest.get("published_at") or "",
        "asset": patch if same_runtime else full,
    }


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(asset: dict, progress=None) -> Path:
    """Fetch one release asset into `_update/` and verify its SHA256."""
    name = str(asset.get("name") or "")
    want = str(asset.get("sha256") or "").lower()
    if not name:
        raise RuntimeError("更新清单缺少资产名")
    dest = STAGING / "download" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    url = f"https://github.com/{REPO}/releases/download/v{asset.get('version')}/{name}"
    say = progress or (lambda _p, _m: None)
    with httpx.Client(proxy=resolve_proxy(), timeout=None,
                      follow_redirects=True) as client:
        with client.stream("GET", url) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            got = 0
            with part.open("wb") as fh:
                for chunk in r.iter_bytes(1 << 20):
                    fh.write(chunk)
                    got += len(chunk)
                    if total:
                        say(0.05 + 0.85 * got / total,
                            f"下载更新… {got // 1048576}MB")
    os.replace(part, dest)
    if want and sha256_file(dest) != want:
        dest.unlink(missing_ok=True)
        raise RuntimeError("更新包校验失败，已删除下载")
    return dest


def stage_patch(zip_path: Path, progress=None) -> Path:
    """Unpack a patch into `_update/pending/` (still not applied).

    Only `backend/` and `frontend/dist/` are taken: a patch must never be able
    to overwrite the interpreter, ffmpeg, models or the user's `localdata/`.
    """
    say = progress or (lambda _p, _m: None)
    pending = STAGING / "pending"
    shutil.rmtree(pending, ignore_errors=True)
    pending.mkdir(parents=True, exist_ok=True)
    root = pending.resolve()
    allowed = ("backend/", "frontend/dist/")
    written = 0
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            rel = member[len("UtaLearnNext/"):] \
                if member.startswith("UtaLearnNext/") else member
            if not rel.startswith(allowed):
                continue
            target = (pending / rel).resolve()
            if not target.is_relative_to(root):
                continue
            if member.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            written += 1
    if not written:
        raise RuntimeError("补丁包里没有 backend/ 或 frontend/dist/")
    say(0.98, "更新已准备好，重启后生效")
    return pending


def mark_pending(version: str) -> None:
    STAGING.mkdir(parents=True, exist_ok=True)
    _state_file().write_text(json.dumps({"version": version, "ready": True}),
                             encoding="utf-8")


def pending_version() -> str | None:
    try:
        state = json.loads(_state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return state.get("version") if state.get("ready") else None


def apply_pending() -> str | None:
    """Swap the staged patch in. Runs at startup, before the server binds.

    The previous app layer is renamed to `app.prev/` first, so a failed start
    can be rolled back; only then is the new one moved into place.
    """
    pending = STAGING / "pending"
    if not pending.is_dir():
        return None
    version = pending_version()

    # backend and frontend/dist are moved one at a time, each with its own
    # backup, so a crash between the two is still recoverable
    for rel in ("backend", "frontend/dist"):
        new = pending / rel
        if not new.exists():
            continue
        live = APP_ROOT / rel
        backup = BACKUP / rel
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(backup, ignore_errors=True)
        if live.exists():
            live.rename(backup)
        new.rename(live)

    shutil.rmtree(STAGING, ignore_errors=True)
    return version


def rollback() -> bool:
    """Restore `app.prev/` over the live app layer."""
    if not BACKUP.is_dir():
        return False
    for rel in ("backend", "frontend/dist"):
        old = BACKUP / rel
        if not old.exists():
            continue
        live = APP_ROOT / rel
        shutil.rmtree(live, ignore_errors=True)
        old.rename(live)
    shutil.rmtree(BACKUP, ignore_errors=True)
    return True
