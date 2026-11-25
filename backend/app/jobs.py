"""Background job registry with cancellation, resource limits and persistence.

A build can take a minute (whisper) or a few seconds (a lyric source), and the
UI polls `/api/jobs/{id}` (or subscribes to `/api/jobs/{id}/events`) so it never
sits on a blocked request.

Three things the old version got wrong and this one fixes:

* **Nothing was cancelled.** Whisper burned a minute of CPU even after the user
  hit 取消, and the result still overwrote the dataset.
* **Nothing was limited.** Two 生成 clicks ran two whisper passes at once; on a
  laptop that is slower than running them one after the other.
* **Nothing survived a restart.** The window closed mid-job and the UI polled a
  job id that no longer existed.

Jobs are grouped by *resource*: `cpu` (transcribe/translate/align), `export`
(headless recorder) and `net` (downloads, searches). Admission is FIFO per
resource, so a long whisper pass never starves an export and vice versa.
"""
from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

from app.paths import DATA_DIR

JobKind = Literal["build", "custom", "realign", "export", "install", "update"]
JobResource = Literal["cpu", "export", "net"]
JobStatus = Literal["queued", "running", "done", "error", "canceled", "interrupted"]

RESOURCE_LIMITS: dict[str, int] = {"cpu": 1, "export": 1, "net": 2}
KEEP_SECONDS = 3600
STATE_FILE = DATA_DIR / ".jobs.json"


class JobCanceled(RuntimeError):
    """Raised inside a worker when the user cancels the job."""


@dataclass
class Job:
    id: str
    kind: str
    resource: str
    status: JobStatus = "queued"
    stage: str = ""
    progress: float = 0.0
    message: str = "排队中…"
    result: dict | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    done: threading.Event = field(default_factory=threading.Event, repr=False)

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "resource": self.resource,
            "status": self.status,
            "stage": self.stage,
            "progress": round(self.progress, 3),
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    # the wire format the existing UI reads (`id`/`status`/`progress`/...)
    def to_api(self) -> dict:
        snap = self.snapshot()
        snap["progress"] = round(max(0.0, min(1.0, self.progress)), 3)
        return snap


JOBS: dict[str, Job] = {}
_LOCK = threading.Lock()
# One FIFO per resource: a blocked `cpu` slot must never hold up a `net` job,
# and jobs on the same resource still start in the order the user created them.
_PENDING: dict[str, deque[str]] = {name: deque() for name in RESOURCE_LIMITS}
_WAKE = threading.Event()
_FUNCS: dict[str, object] = {}
_RUNNING: dict[str, int] = {name: 0 for name in RESOURCE_LIMITS}
_dispatcher: threading.Thread | None = None
_save_timer: threading.Timer | None = None


def _prune() -> None:
    now = time.time()
    for jid, job in list(JOBS.items()):
        if job.status in ("done", "error", "canceled", "interrupted") \
                and job.finished_at and now - job.finished_at > KEEP_SECONDS:
            JOBS.pop(jid, None)
            _FUNCS.pop(jid, None)


def _save_now() -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = [job.snapshot() for job in JOBS.values()]
        tmp = STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except OSError:
        # a read-only data folder must never take a job down with it
        pass


def _save_soon() -> None:
    """Debounce disk writes: progress updates arrive several times a second."""
    global _save_timer
    if _save_timer is not None and _save_timer.is_alive():
        return
    _save_timer = threading.Timer(1.0, _save_now)
    _save_timer.daemon = True
    _save_timer.start()


def load_state() -> int:
    """Reload jobs from the previous run, marking unfinished ones interrupted.

    The first start after an upgrade has no state file, which is normal; a
    corrupt one is dropped rather than crashing the server.
    """
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    restored = 0
    with _LOCK:
        for item in raw if isinstance(raw, list) else []:
            try:
                job = Job(
                    id=item["id"], kind=item.get("kind", "build"),
                    resource=item.get("resource", "cpu"),
                    status=item.get("status", "interrupted"),
                    stage=item.get("stage", ""),
                    progress=float(item.get("progress") or 0),
                    message=item.get("message", ""),
                    result=item.get("result"),
                    error=item.get("error"),
                    created_at=float(item.get("created_at") or time.time()),
                    started_at=item.get("started_at"),
                    finished_at=item.get("finished_at"),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if job.status in ("queued", "running"):
                job.status = "interrupted"
                job.message = "程序退出时未完成，可重新生成"
                job.finished_at = time.time()
            job.done.set()
            JOBS[job.id] = job
            restored += 1
    if restored:
        _save_now()
    return restored


def create(kind: str, resource: str = "cpu") -> str:
    if resource not in RESOURCE_LIMITS:
        resource = "cpu"
    jid = uuid.uuid4().hex[:12]
    with _LOCK:
        _prune()
        JOBS[jid] = Job(id=jid, kind=kind, resource=resource)
    _save_soon()
    return jid


def _check_cancel(job: Job) -> None:
    if job.cancel.is_set():
        raise JobCanceled("已取消")


def update(jid: str, progress: float | None = None, message: str | None = None,
           stage: str | None = None) -> None:
    with _LOCK:
        job = JOBS.get(jid)
        if not job:
            return
        if progress is not None:
            job.progress = max(0.0, min(1.0, progress))
        if message is not None:
            job.message = message
        if stage is not None:
            job.stage = stage
        if job.status == "queued":
            job.status = "running"
            job.started_at = time.time()
    _save_soon()


def finish(jid: str, result: dict) -> None:
    with _LOCK:
        job = JOBS.get(jid)
        if not job:
            return
        job.status = "done"
        job.progress = 1.0
        job.message = "完成"
        job.result = result
        job.finished_at = time.time()
        job.done.set()
    _FUNCS.pop(jid, None)
    _save_now()


def fail(jid: str, error: str) -> None:
    with _LOCK:
        job = JOBS.get(jid)
        if not job:
            return
        job.status = "error"
        job.message = error
        job.error = error
        job.finished_at = time.time()
        job.done.set()
    _FUNCS.pop(jid, None)
    _save_now()


def mark_canceled(jid: str) -> None:
    with _LOCK:
        job = JOBS.get(jid)
        if not job:
            return
        job.status = "canceled"
        job.message = "已取消"
        job.finished_at = time.time()
        job.done.set()
    _FUNCS.pop(jid, None)
    _save_now()


def cancel(jid: str) -> bool:
    """Ask a job to stop. A queued job never starts; a running one stops at its
    next progress report (every long loop reports at least once a second)."""
    with _LOCK:
        job = JOBS.get(jid)
        if not job or job.status in ("done", "error", "canceled", "interrupted"):
            return False
        job.cancel.set()
        queued = job.status == "queued"
        if queued:
            # remove it from the resource FIFO so admission never has to skip it
            for pending in _PENDING.values():
                try:
                    pending.remove(jid)
                except ValueError:
                    pass
            _mark_canceled_locked(job)
    if queued:
        _save_now()
    return True


def get(jid: str) -> dict | None:
    """The wire snapshot the UI polls (kept compatible with the old shape)."""
    with _LOCK:
        job = JOBS.get(jid)
        if not job:
            return None
        return job.to_api()


def snapshot(jid: str) -> dict | None:
    with _LOCK:
        job = JOBS.get(jid)
        return job.snapshot() if job else None


def list_jobs(active_only: bool = False) -> list[dict]:
    with _LOCK:
        jobs = sorted(JOBS.values(), key=lambda j: j.created_at)
    if active_only:
        jobs = [j for j in jobs if j.status in ("queued", "running")]
    return [j.to_api() for j in jobs]


def _dispatch() -> None:
    """Start every job whose resource has a free slot, each on its own thread.

    A single inline worker was the first version of this and it serialised
    *everything*: a three-minute whisper pass blocked a 2 MB pack download.
    One thread per admitted job, with admission decided per resource, keeps the
    cpu job on one core group and the download running beside it.
    """
    while True:
        started = False
        with _LOCK:
            for resource, limit in RESOURCE_LIMITS.items():
                pending = _PENDING[resource]
                while pending and _RUNNING[resource] < limit:
                    jid = pending.popleft()
                    job = JOBS.get(jid)
                    fn = _FUNCS.get(jid)
                    if job is None or fn is None:
                        continue
                    if job.cancel.is_set():
                        _mark_canceled_locked(job)
                        continue
                    _RUNNING[resource] += 1
                    threading.Thread(
                        target=_run_slot, args=(job, fn, resource),
                        daemon=True, name=f"job-{jid}").start()
                    started = True
        if not started:
            _WAKE.wait(0.2)
            _WAKE.clear()


def _mark_canceled_locked(job: Job) -> None:
    job.status = "canceled"
    job.message = "已取消"
    job.finished_at = time.time()
    job.done.set()
    _FUNCS.pop(job.id, None)


def _run_slot(job: Job, fn, resource: str) -> None:
    try:
        _run_one(job, fn)
    finally:
        with _LOCK:
            _RUNNING[resource] -= 1
        _WAKE.set()


def _run_one(job: Job, fn) -> None:
    def progress(frac: float, msg: str) -> None:
        # the cheapest possible cancellation point: every loop already reports
        _check_cancel(job)
        update(job.id, frac, msg)

    try:
        update(job.id, 0.01, "开始…")
        _check_cancel(job)
        result = fn(progress)
        _check_cancel(job)
        finish(job.id, result)
    except JobCanceled:
        mark_canceled(job.id)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        fail(job.id, str(e) or e.__class__.__name__)


def _ensure_dispatcher() -> None:
    global _dispatcher
    if _dispatcher is not None and _dispatcher.is_alive():
        return
    _dispatcher = threading.Thread(target=_dispatch, daemon=True, name="job-dispatch")
    _dispatcher.start()


def run(jid: str, fn, resource: str | None = None) -> None:
    """Queue `fn(progress)`; `progress(frac, msg)` reports and checks cancel."""
    with _LOCK:
        job = JOBS.get(jid)
        if job is None:
            return
        if resource:
            job.resource = resource if resource in RESOURCE_LIMITS else "cpu"
        _FUNCS[jid] = fn
        _PENDING[job.resource].append(jid)
    _ensure_dispatcher()
    _WAKE.set()


def events(jid: str, timeout: float = 30.0):
    """Yield job snapshots as they change — the SSE body.

    The stream ends when the job reaches a terminal state, so the client can
    stop reconnecting instead of leaving a dangling EventSource.
    """
    last = None
    deadline = time.time() + timeout
    while True:
        snap = snapshot(jid)
        if snap is None:
            yield {"event": "error", "data": {"detail": "任务不存在或已过期"}}
            return
        if snap != last:
            yield {"event": "job", "data": snap}
            last = snap
        if snap["status"] in ("done", "error", "canceled", "interrupted"):
            return
        if time.time() > deadline:
            # let the browser reconnect; a job can legitimately run for minutes
            yield {"event": "ping", "data": {"id": jid}}
            deadline = time.time() + timeout
        time.sleep(0.5)
