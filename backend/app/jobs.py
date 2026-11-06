"""Tiny in-process job registry for long-running builds.

A build can take a minute (whisper) or a few seconds (a lyric source). The UI
polls `/api/jobs/{id}` so it never sits on a blocked request.
"""
from __future__ import annotations

import threading
import time
import traceback
import uuid

JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()
KEEP_SECONDS = 3600


def _prune() -> None:
    now = time.time()
    for jid, job in list(JOBS.items()):
        if job["status"] in ("done", "error") and now - job["updated"] > KEEP_SECONDS:
            JOBS.pop(jid, None)


def create(kind: str) -> str:
    jid = uuid.uuid4().hex[:12]
    with _LOCK:
        _prune()
        JOBS[jid] = {
            "id": jid, "kind": kind, "status": "queued",
            "progress": 0.0, "message": "排队中…",
            "result": None, "error": None,
            "created": time.time(), "updated": time.time(),
        }
    return jid


def update(jid: str, progress: float | None = None, message: str | None = None) -> None:
    with _LOCK:
        job = JOBS.get(jid)
        if not job:
            return
        if progress is not None:
            job["progress"] = round(max(0.0, min(1.0, progress)), 3)
        if message is not None:
            job["message"] = message
        # a queued job that reports progress is running
        if job["status"] == "queued":
            job["status"] = "running"
        job["updated"] = time.time()


def finish(jid: str, result: dict) -> None:
    with _LOCK:
        job = JOBS.get(jid)
        if job:
            job.update(status="done", progress=1.0, message="完成",
                       result=result, updated=time.time())


def fail(jid: str, error: str) -> None:
    with _LOCK:
        job = JOBS.get(jid)
        if job:
            job.update(status="error", message=error, error=error,
                       updated=time.time())


def get(jid: str) -> dict | None:
    with _LOCK:
        job = JOBS.get(jid)
        return dict(job) if job else None


def run(jid: str, fn) -> None:
    """Run `fn(progress)` on a worker thread; `progress(frac, msg)` reports."""
    def progress(frac: float, msg: str) -> None:
        update(jid, frac, msg)

    def worker() -> None:
        try:
            update(jid, 0.01, "开始…")
            result = fn(progress)
            finish(jid, result)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            fail(jid, str(e) or e.__class__.__name__)

    threading.Thread(target=worker, daemon=True, name=f"job-{jid}").start()
