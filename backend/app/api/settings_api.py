"""设置页 API:读写设置、探测代理、查看路径与构建信息。"""
from __future__ import annotations

import platform
import socket
import time

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app import guard, legacy_import, logs, packs, settings, telemetry
from app.paths import APP_ROOT, DATA_DIR, EXPORT_DIR
from app.schemas import ProxyTestRequest, SettingsPatch
from app.sources import resolve_proxy
from app.version import APP_NAME, APP_VERSION

router = APIRouter()


@router.get("/api/settings")
def api_settings_get():
    data = settings.load()
    # the install id is only meaningful while telemetry is on
    if not data.get("telemetry"):
        data["install_id"] = ""
    return data


@router.patch("/api/settings")
def api_settings_patch(patch: SettingsPatch):
    # `patch` is a Pydantic model (extra="allow"), never a dict: iterating it
    # yields (name, value) pairs and `.get` does not exist. Turn it into a
    # plain mapping once, then validate that mapping.
    data = patch.model_dump()
    allowed = set(settings.DEFAULTS)
    bad = set(data) - allowed
    if bad:
        raise HTTPException(status_code=400, detail=f"未知设置项: {sorted(bad)}")
    mode = data.get("proxy_mode")
    if mode is not None and mode not in ("auto", "system", "manual", "off"):
        raise HTTPException(status_code=400, detail="代理模式无效")
    if data.get("long_vowel") not in (None, "ou", "macron", "oo"):
        raise HTTPException(status_code=400, detail="长音写法无效")
    if data.get("particle_reading") not in (None, "pron", "literal"):
        raise HTTPException(status_code=400, detail="助词读法无效")
    if data.get("theme") not in (None, "system", "light", "dark"):
        raise HTTPException(status_code=400, detail="主题无效")
    if data.get("ui_font") not in (None, "s", "m", "l"):
        raise HTTPException(status_code=400, detail="界面字号无效")
    if data.get("play_style") not in (None, "default", "karaoke"):
        raise HTTPException(status_code=400, detail="播放样式无效")
    if data.get("karaoke_color") not in (None, "coral", "blue", "green"):
        raise HTTPException(status_code=400, detail="卡拉OK主题色无效")
    zoom = data.get("page_zoom")
    if zoom is not None and not isinstance(zoom, (int, float)):
        raise HTTPException(status_code=400, detail="页面缩放无效")
    if zoom is not None and not 0.8 <= float(zoom) <= 1.5:
        raise HTTPException(status_code=400, detail="页面缩放需在 0.8 - 1.5 之间")
    return settings.save(data)


@router.post("/api/settings/reset")
def api_settings_reset():
    return settings.reset()


@router.post("/api/settings/test-proxy")
def api_settings_test_proxy(payload: ProxyTestRequest | None = None):
    """Probe the proxy the app would use right now.

    A manual URL in the body is tested *without* being saved, so the settings
    page can validate a value before the user commits to it.
    """
    manual = (payload.proxy_url if payload else None)
    proxy = (manual or "").strip() or resolve_proxy()
    try:
        with httpx.Client(proxy=proxy, timeout=8.0, follow_redirects=True) as c:
            r = c.get("https://www.google.com/generate_204")
        return {"ok": r.status_code < 400, "proxy": proxy,
                "status": r.status_code}
    except httpx.HTTPError as e:
        return {"ok": False, "proxy": proxy, "error": str(e)}


@router.get("/api/about")
def api_about():
    """Everything 设置 → 关于 shows, plus the paths a bug report needs."""
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "python": platform.python_version(),
        "os": platform.platform(),
        "hostname": socket.gethostname(),
        "paths": {
            "app": str(APP_ROOT),
            "data": str(DATA_DIR),
            "exports": str(EXPORT_DIR),
        },
        "packs": {
            "custom_lyrics": packs.custom_lyrics_installed(),
            "chromium": packs.chromium_installed(),
        },
        "dev": guard.DEV,
    }


@router.get("/api/diagnostics")
def api_diagnostics():
    """Build the support zip on demand; never uploaded anywhere automatically."""
    stamp = __import__("time").strftime("%Y%m%d-%H%M%S")
    dest = DATA_DIR / "_diagnostics" / f"diagnostics-{stamp}.zip"
    logs.build_bundle(dest)
    return FileResponse(dest, media_type="application/zip", filename=dest.name)


@router.get("/api/telemetry/payload")
def api_telemetry_payload():
    """Exactly what a heartbeat would send — shown in 设置 → 关于."""
    return {"enabled": telemetry.enabled(), "url": telemetry.TELEMETRY_URL,
            "payload": telemetry.payload()}


@router.post("/api/system/focus")
def api_system_focus():
    """第二实例把已有窗口叫到前台时调用。

    桌面外壳在 `localdata/_ui/port.txt` 里发布端口,第二个进程读它、POST
    这里,然后退出。这里只记一个时间戳:真正的"显示窗口"由外壳自己轮询。
    """
    settings.save({"focus_requested_at": time.time()})
    return {"focused": True}


@router.get("/api/legacy/scan")
def api_legacy_scan():
    """旧版本数据:扫描同级目录(§5.5.3)。"""
    return {"candidates": legacy_import.candidates()}


@router.post("/api/legacy/import")
def api_legacy_import(payload: dict):
    path = (payload.get("path") or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="缺少目录")
    try:
        return legacy_import.import_from(path, bool(payload.get("move")))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="目录不存在") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
