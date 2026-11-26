"""扩展包状态与安装路由:自定义歌词模型包、Chromium 导出包。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import jobs, packs
from app.paths import APP_ROOT

router = APIRouter()


def _pack_state(key: str) -> dict:
    """One row of 设置 → 扩展包: installed?, where, and its real size.

    The sizes used to be prose ("约 500MB") that drifted away from the actual
    asset; the page now shows what is on disk (or the approximate download
    size when the pack is absent), so 安装 / 删除 has something to report.
    """
    if key == "custom_lyrics":
        installed = packs.custom_lyrics_installed()
        path = packs.APP_ROOT / "models"
    else:
        installed = packs.chromium_installed()
        path = packs.browsers_dir()
    return {
        "key": key,
        "installed": installed,
        "path": str(path),
        "size": packs.installed_size("models" if key == "custom_lyrics" else "browsers"),
    }


@router.get("/api/models/status")
def api_model_status():
    return {"installed": packs.custom_lyrics_installed(),
            "whisper": packs.whisper_installed(),
            "translate": packs.translate_installed(),
            "path": str(APP_ROOT / "models"),
            "asset": packs.CUSTOM_ASSET}


@router.get("/api/packs/status")
def api_packs_status():
    """Both extension packs, with the size the settings page displays."""
    return {"packs": [_pack_state("custom_lyrics"), _pack_state("chromium")]}


@router.delete("/api/packs/{key}")
def api_packs_remove(key: str):
    """Delete an installed pack so it can be re-downloaded."""
    if key not in ("custom_lyrics", "chromium"):
        raise HTTPException(status_code=404, detail="没有这个扩展包")
    removed = packs.remove("models" if key == "custom_lyrics" else "browsers")
    if not removed:
        raise HTTPException(status_code=409, detail="扩展包未安装")
    return {"removed": True, **_pack_state(key)}


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
