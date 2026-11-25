"""扩展包状态与安装路由:自定义歌词模型包、Chromium 导出包。"""
from __future__ import annotations

from fastapi import APIRouter

from app import jobs, packs
from app.paths import APP_ROOT

router = APIRouter()


@router.get("/api/models/status")
def api_model_status():
    return {"installed": packs.custom_lyrics_installed(),
            "whisper": packs.whisper_installed(),
            "translate": packs.translate_installed(),
            "path": str(APP_ROOT / "models"),
            "asset": packs.CUSTOM_ASSET}


@router.post("/api/models/install")
def api_model_install():
    """Download + unpack the custom-lyrics extension pack in the background."""
    if packs.custom_lyrics_installed():
        return {"job_id": None, "installed": True}
    jid = jobs.create("install", "net")

    def work(progress):
        progress(0.05, "查询最新发行版…")
        path = packs.install_custom_lyrics(progress)
        progress(0.98, "安装完成")
        return {"installed": True, "path": str(path)}

    jobs.run(jid, work)
    return {"job_id": jid}


@router.post("/api/export/install-chromium")
def api_export_install_chromium():
    """Download + unpack the bundled-Chromium extension pack.

    Used when the machine has no usable Chromium-core browser *and* the
    playwright route can't help (e.g. its download is blocked). The zip drops a
    `browsers/` folder next to the app, exactly like the manual extension.
    """
    if packs.chromium_installed():
        return {"job_id": None, "installed": True}
    jid = jobs.create("install", "net")

    def work(progress):
        progress(0.05, "查询最新发行版…")
        path = packs.install_chromium(progress)
        progress(0.98, "安装完成")
        return {"installed": True, "needs_restart": True, "path": str(path)}

    jobs.run(jid, work)
    return {"job_id": jid}
