"""Uta Learn Next 后端入口:装配路由、中间件与静态 SPA。

两个业务:
1. **配置** — 从 QQ 音乐 / 酷狗 / Lrclib 取歌词,或用手动上传的音频 + 歌词,
   经切片 whisper 转写与全局假名对齐得到逐字时间轴。
2. **播放** — 把数据集(`song_data.json` + `audio.mp3`)交给卡拉 OK 舞台,
   并在 `frontend/dist` 存在时托管构建好的 SPA。

数据集是 `DATA_DIR` 下的一个文件夹;以 `_` 开头的文件夹是内部目录
(上传暂存、舞台背景),永远不当作歌曲列出。

路由按领域放在 `app/api/` 下,这里只做装配 —— 每次改路由都动同一个千行文件
既容易冲突,也让测试只能整包启动。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import guard, jobs, logs, telemetry
from app.api import config as config_api
from app.api import export_api, packs_api, settings_api
from app.api import songs as songs_api
from app.api import stage as stage_api
from app.datasets import prune_uploads
from app.paths import APP_ROOT, DATA_DIR, DIST_DIR, EXPORT_DIR
from app.version import APP_NAME, APP_VERSION

# `main.TOKEN` / `main.DEV` stay importable: the guard lives in app.guard now,
# but tests and older call sites read them off the app module.
DEV, TOKEN, LOCAL_HOSTS = guard.DEV, guard.TOKEN, guard.LOCAL_HOSTS


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logs.setup()
    logs.log().info("启动 %s %s", APP_NAME, APP_VERSION)
    # jobs from the previous run come back as `interrupted` so the UI can show
    # "程序退出时未完成" instead of a 404 for a job id it still remembers
    restored = jobs.load_state()
    if restored:
        print(f"[uta] 恢复了 {restored} 条任务记录")
    # staging uploads are only meaningful while a song is being configured
    try:
        removed = prune_uploads()
        if removed:
            print(f"[uta] 清理了 {removed} 个过期上传")
    except Exception:  # noqa: BLE001
        pass
    print(f"[uta] 程序目录 {APP_ROOT}")
    print(f"[uta] 数据目录 {DATA_DIR}")
    print(f"[uta] 导出目录 {EXPORT_DIR}")
    telemetry.schedule()
    yield


class _QuietAccessFilter(logging.Filter):
    """Drop the UI's polling lines from the console window.

    The UI polls `/api/jobs/{id}` every ~1s while a build/export runs and hits a
    few read-only endpoints on a timer; each one logs a full uvicorn access line
    and floods the console. Only true polling endpoints are filtered —
    list/detail/mutation routes stay visible.
    """

    _NOISY = ("/api/jobs/", "/api/export/env", "/api/models/status")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        # access lines look like: `127.0.0.1:12345 - "GET /api/jobs/x HTTP/1.1" 200`
        return not any(path in msg for path in self._NOISY)


logging.getLogger("uvicorn.access").addFilter(_QuietAccessFilter())

app = FastAPI(title="Uta Learn Next API", lifespan=lifespan)

guard.install(app)
for router in (config_api.router, songs_api.router, packs_api.router,
               export_api.router, settings_api.router, stage_api.router):
    app.include_router(router)

# SPA last, so every /api route above wins over the static file fallback
if (DIST_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="spa")
else:
    @app.get("/__no_dist")
    def _no_dist():  # pragma: no cover - dev only
        return JSONResponse({"detail": "frontend/dist 未构建，请用 dev.cmd 启动"},
                            status_code=503)
