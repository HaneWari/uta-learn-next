"""播放页路由:首页、版本、音频与舞台背景。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from app import guard, repo
from app.datasets import audio_mime, dataset, find_audio, list_datasets
from app.paths import DIST_DIR, NO_CACHE, UI_DIR
from app.version import APP_NAME, APP_VERSION

router = APIRouter()

BG_META = UI_DIR / "background.json"
BG_MAX = 12 * 1024 * 1024
BG_MEDIA = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp"}


@router.get("/")
def health():
    # read the dist folder through the app module when it is importable, so a
    # test (or a relocated build) that patches `main.DIST_DIR` is honoured
    # instead of the constant bound at import time
    dist = DIST_DIR
    app_module = sys.modules.get("main")
    if app_module is not None:
        dist = getattr(app_module, "DIST_DIR", dist)
    if (dist / "index.html").exists():
        return HTMLResponse(guard.index_html(dist), headers=NO_CACHE)
    return {"status": "ok", "songs": list_datasets()}


@router.get("/api/version")
def api_version():
    """Identity of the running build: shown in 设置 → 关于, used by the updater."""
    return {"name": APP_NAME, "version": APP_VERSION,
            "schema_version": repo.SCHEMA_VERSION}


@router.get("/api/audio/{name}")
def api_audio(name: str):
    path = find_audio(dataset(name))
    if path is None:
        raise HTTPException(status_code=404, detail="这个数据集没有音频")
    return FileResponse(path, media_type=audio_mime(path), headers=NO_CACHE)


def _bg_state() -> dict:
    try:
        meta = json.loads(BG_META.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"mode": "default", "url": None}
    name = meta.get("file") or ""
    path = UI_DIR / name
    if meta.get("mode") != "custom" or not name or not path.exists():
        return {"mode": "default", "url": None}
    return {"mode": "custom", "url": f"/api/ui/background/image?v={int(path.stat().st_mtime)}"}


@router.get("/api/ui/background")
def api_bg_get():
    return _bg_state()


@router.post("/api/ui/background")
async def api_bg_upload(file: UploadFile):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in BG_MEDIA:
        raise HTTPException(status_code=400, detail="请上传 jpg / png / webp 图片")
    UI_DIR.mkdir(parents=True, exist_ok=True)
    dest = UI_DIR / f"background{ext}"
    size = 0
    with dest.open("wb") as fh:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > BG_MAX:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="图片超过 12MB")
            fh.write(chunk)
    # a stale image of another extension would otherwise linger and could be
    # served by a later metadata read
    for other in BG_MEDIA:
        p = UI_DIR / f"background{other}"
        if p != dest and p.exists():
            p.unlink(missing_ok=True)
    BG_META.write_text(json.dumps({"mode": "custom", "file": dest.name}),
                       encoding="utf-8")
    return _bg_state()


@router.delete("/api/ui/background")
def api_bg_reset():
    for ext in BG_MEDIA:
        (UI_DIR / f"background{ext}").unlink(missing_ok=True)
    BG_META.unlink(missing_ok=True)
    return {"mode": "default", "url": None}


@router.get("/api/ui/background/image")
def api_bg_image():
    state = _bg_state()
    if not state["url"]:
        raise HTTPException(status_code=404, detail="还没有自定义背景")
    try:
        meta = json.loads(BG_META.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="还没有自定义背景") from None
    path = UI_DIR / (meta.get("file") or "")
    if not path.exists():
        raise HTTPException(status_code=404, detail="还没有自定义背景")
    media = BG_MEDIA.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media, headers=NO_CACHE)
