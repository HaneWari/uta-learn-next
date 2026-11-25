"""导出环境修复与视频导出路由。"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app import export, jobs, render_frames, settings
from app.datasets import audio_duration, dataset, find_audio, meta_flag
from app.paths import APP_ROOT, BASE_URL, EXPORT_DIR
from app.schemas import ExportRequest, RevealRequest

router = APIRouter()
DEFAULT_PRESET_FOR_EXPORT = export.DEFAULT_PRESET


@router.get("/api/export/env")
def api_export_env():
    """Deep export-environment probe run on demand (not cached).

    The frontend calls this when the user clicks 导出视频, so the answer is
    always about the machine *right now* — a browser installed since startup
    shows up without an app restart.
    """
    return export.env_check()


@router.get("/api/export/presets")
def api_export_presets():
    """The three fixed-60fps presets, with a time estimate for a given song."""
    return {
        "default": export.DEFAULT_PRESET,
        "fps": export.FPS,
        "presets": [
            {"id": key, **value, "width_px": value["width"] * value["scale"],
             "height_px": value["height"] * value["scale"]}
            for key, value in export.PRESETS.items()
        ],
    }


@router.post("/api/export/fix")
def api_export_fix():
    """Repair whatever the env probe flagged, in one background job.

    Each missing piece gets its own fix — ffmpeg is dropped into `bin/` from
    the same slim build the portable packer uses, playwright is pip-installed
    and its matching chromium pulled, then the browser is re-probed. A fix
    that leaves `state == "ok"` hands control back to the export right away;
    one that still can't launch the browser reports `needs_extension` so the
    modal can promote the Chromium pack.
    """
    jid = jobs.create("export", "export")

    def work(progress):
        import httpx

        c = export.env_check()
        checks = c["checks"]

        # 1. ffmpeg — the mux tool the packer puts in bin/; a missing copy just
        #    needs the slim essentials build unzipped next to the app.
        if not checks["ffmpeg"]:
            progress(0.08, "下载 ffmpeg…")
            try:
                from tools.build_portable import FFMPEG_ZIP
            except Exception:  # noqa: BLE001
                FFMPEG_ZIP = ("https://www.gyan.dev/ffmpeg/builds/"
                              "ffmpeg-release-essentials.zip")
            bin_dir = APP_ROOT / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            buf = io.BytesIO()
            with httpx.Client(timeout=None, follow_redirects=True) as hc:
                with hc.stream("GET", FFMPEG_ZIP) as r:
                    r.raise_for_status()
                    for chunk in r.iter_bytes(1 << 20):
                        buf.write(chunk)
            buf.seek(0)
            with zipfile.ZipFile(buf) as z:
                for member in z.namelist():
                    name = Path(member).name
                    if name in ("ffmpeg.exe", "ffprobe.exe"):
                        with z.open(member) as src, (bin_dir / name).open("wb") as dst:
                            shutil.copyfileobj(src, dst)
            progress(0.3, "ffmpeg 已就位")

        # 2. playwright — the package itself, then a browser it can drive.
        progress(0.4, "检查 Playwright…")
        if not checks["playwright"]:
            progress(0.45, "安装 playwright …")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q", "playwright"],
                check=True, capture_output=True)
        # launch failing means no usable browser; launch succeeding but
        # record_video failing means the playwright ffmpeg component is
        # missing — both are fixed by `playwright install`
        if not checks["browser_launch"] or not checks.get("record_video", True):
            progress(0.55, "下载 Chromium（约 130MB，请稍候）…")
            try:
                subprocess.run(
                    # `record_video` needs playwright's own ffmpeg-* build too —
                    # `install chromium` alone leaves new_context() demanding
                    # ffmpeg-win64.exe that was never downloaded
                    [sys.executable, "-m", "playwright", "install",
                     "chromium", "ffmpeg"],
                    check=True, capture_output=True, env=dict(os.environ))
            except Exception:  # noqa: BLE001
                # playwright's own download being blocked is exactly the case
                # the bundled pack exists for — report, don't fail hard
                progress(0.8, "playwright 下载浏览器失败，改用扩展包…")

        progress(0.9, "验证环境…")
        c = export.env_check()
        progress(0.98, "完成")
        return {"ok": c["ok"], "state": c["state"], "env": c,
                "needs_restart": c["ok"],
                "needs_extension": c["state"] in ("no_browser", "no_playwright",
                                                 "no_recorder")}

    jobs.run(jid, work)
    return {"job_id": jid}


@router.get("/api/exports")
def api_exports():
    if not EXPORT_DIR.is_dir():
        return []
    out = []
    for f in sorted(EXPORT_DIR.glob("*.mp4"), key=lambda x: -x.stat().st_mtime):
        st = f.stat()
        out.append({
            "file": f.name,
            "size": st.st_size,
            "created": int(st.st_mtime),
            "url": f"/api/exports/{f.name}",
        })
    return out


@router.post("/api/exports/reveal")
def api_export_reveal(payload: RevealRequest | None = None):
    """Open the export folder in the OS file manager.

    Only the folder itself — no path from the request is honoured, so this can
    never be turned into "open anything on this machine".
    """
    import subprocess
    import sys

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    name = (payload.file if payload else None)
    if sys.platform == "win32":
        if name:
            subprocess.Popen(["explorer", "/select,", str(EXPORT_DIR / name)])
        else:
            subprocess.Popen(["explorer", str(EXPORT_DIR)])
    elif sys.platform == "darwin":
        target = str(EXPORT_DIR / name) if name else str(EXPORT_DIR)
        subprocess.Popen(["open", "-R", target] if name else ["open", target])
    else:
        subprocess.Popen(["xdg-open", str(EXPORT_DIR)])
    return {"opened": str(EXPORT_DIR)}


def _base_url(request: Request) -> str:
    """Where the recorder should open the stage.

    The launcher picks the first free port in 8000–8010, so a hardcoded 8000
    meant an export launched on 8011 recorded a dead page. Prefer the explicit
    env override, then the address the request itself arrived on.
    """
    if BASE_URL:
        return BASE_URL
    return str(request.base_url).rstrip("/")


@router.post("/api/export")
async def api_export(payload: ExportRequest, request: Request):
    """Record the stage for one dataset and mux its audio into an MP4."""
    name = (payload.song or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="缺少 song")
    folder = dataset(name)
    data_path = folder / "song_data.json"
    if not data_path.exists():
        raise HTTPException(status_code=404, detail="song_data.json missing")

    import json

    meta = json.loads(data_path.read_text(encoding="utf-8")).get("meta", {})
    audio = find_audio(folder)

    # The recording has to last as long as the *audio*, not as long as the lyric
    # timeline: a trimmed intro or a different edit makes those differ by tens of
    # seconds, and recording to the lyric length silently cut the song short.
    timeline = float(meta.get("duration_seconds") or 0)
    duration = (audio_duration(audio) if audio else 0.0) or timeline
    if duration <= 0:
        raise HTTPException(status_code=400, detail="这个数据集没有时间轴，无法导出")

    # a clip export: both ends must sit inside the audio, and the order matters
    try:
        clip_start = max(0.0, float(payload.clip_start or 0))
    except (TypeError, ValueError):
        clip_start = 0.0
    try:
        requested = float(payload.clip_end or 0)
    except (TypeError, ValueError):
        requested = 0.0
    clip_end = duration if requested <= 0 else min(requested, duration)
    if clip_end - clip_start < 1.0:
        raise HTTPException(status_code=400, detail="片段至少要有 1 秒")
    duration = clip_end - clip_start

    preset_name = payload.preset or DEFAULT_PRESET_FOR_EXPORT
    if preset_name not in export.PRESETS:
        preset_name = DEFAULT_PRESET_FOR_EXPORT

    safe = re.sub(r"[^\w.\-]+", "-", name)[:60]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = EXPORT_DIR / f"{safe}-{stamp}.mp4"
    # The recorder opens a fresh browser profile that cannot see the user's
    # localStorage, so every view flag has to travel in the page URL. The
    # dataset's `meta.view` is the source of truth now; the body's
    # `hide_cards` is only a fallback for callers predating that.
    view = meta.get("view") or {}
    hide_cards = view.get("cards") is False or bool(payload.hide_cards)
    hide_trans = view.get("translation") is False or meta_flag(name, "trans_hidden")

    jid = jobs.create("export", "export")

    def work(progress):
        # 兼容模式 keeps the old screen recorder for machines where frame
        # capture misbehaves; the default is the deterministic frame renderer
        compat = bool(settings.get("export_compat", False))
        renderer = export.render if compat else render_frames.render
        renderer(
            base_url=_base_url(request),
            song=name,
            audio=audio,
            out=out,
            duration=duration,
            progress=progress,
            preset_name=preset_name,
            clip_start=clip_start,
            extra_query=("&hidecards=1" if hide_cards else "")
            + ("&hidetrans=1" if hide_trans else ""),
            **({} if compat else {"pages": int(settings.get("export_pages", 3) or 3)}),
        )
        return {"file": out.name, "url": f"/api/exports/{out.name}",
                "size": out.stat().st_size, "duration": duration,
                "dir": str(out.parent), "path": str(out), "fps": export.FPS,
                "renderer": "compat" if compat else "frames",
                "preset": preset_name, "clip_start": clip_start,
                "width": export.preset(preset_name)["width"]
                * export.preset(preset_name)["scale"],
                "height": export.preset(preset_name)["height"]
                * export.preset(preset_name)["scale"]}

    jobs.run(jid, work)
    return {"job_id": jid, "file": out.name}


@router.get("/api/exports/{filename}")
def api_export_file(filename: str):
    if not re.fullmatch(r"[\w.\-]+\.mp4", filename):
        raise HTTPException(status_code=400, detail="bad filename")
    path = EXPORT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, media_type="video/mp4", filename=filename)


@router.delete("/api/exports/{filename}")
def api_export_delete(filename: str):
    if not re.fullmatch(r"[\w.\-]+\.mp4", filename):
        raise HTTPException(status_code=400, detail="bad filename")
    path = EXPORT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="not found")
    path.unlink()
    return {"deleted": filename}
