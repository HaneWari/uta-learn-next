"""Anonymous usage heartbeat: how many installs run which version.

Deliberately tiny: one request per day per install, three fields, sent from
Python (not the web page) so there is no cookie or browser fingerprint. No
song title, lyric, file path, username, search keyword or feature usage ever
leaves the machine — see PRIVACY.md.

A heartbeat is skipped entirely in dev, in CI, when `UTALEARN_TELEMETRY=0`, or
when the user turned it off in 设置. Failure is silent: no retry, no queue, no
toast. The goal is a rough user count, and a missing data point costs nothing.
"""
from __future__ import annotations

import datetime as dt
import os
import platform
import threading
import uuid

import httpx

from app import settings
from app.sources import resolve_proxy
from app.version import APP_VERSION

TELEMETRY_URL = os.environ.get(
    "UTALEARN_TELEMETRY_URL", "https://stats.kibicloud.top/v1/ping")
START_DELAY = 60.0


def os_bucket() -> str:
    if platform.system() != "Windows":
        return "other"
    try:
        release = platform.release()          # 10 / 11
        if release in ("10", "11"):
            return f"win{release}"
    except Exception:  # noqa: BLE001
        pass
    return "other"


def enabled() -> bool:
    if os.environ.get("UTALEARN_DEV") == "1":
        return False
    if os.environ.get("UTALEARN_TELEMETRY") == "0":
        return False
    if os.environ.get("CI"):
        return False
    return bool(settings.get("telemetry", True))


def install_id() -> str:
    """Stable random UUIDv4 — unrelated to hardware, account or username."""
    current = settings.get("install_id") or ""
    if current:
        return current
    fresh = str(uuid.uuid4())
    settings.save({"install_id": fresh})
    return fresh


def payload() -> dict:
    return {"iid": install_id(), "v": APP_VERSION, "os": os_bucket()}


def should_send(now: dt.date | None = None) -> bool:
    today = (now or dt.date.today()).isoformat()
    return settings.get("telemetry_last_day") != today


def send(now: dt.date | None = None) -> bool:
    """POST one heartbeat. Returns True when it was accepted."""
    if not enabled():
        return False
    today = (now or dt.date.today()).isoformat()
    if not should_send(now):
        return False
    try:
        with httpx.Client(proxy=resolve_proxy(), timeout=8.0) as client:
            r = client.post(TELEMETRY_URL, json=payload())
        if r.status_code >= 400:
            # a rejected heartbeat still counts as "tried today": retrying a
            # 400 would hammer the endpoint for no benefit
            settings.save({"telemetry_last_day": today})
            return False
    except httpx.HTTPError:
        # offline / blocked / proxied away — give up quietly for today
        return False
    settings.save({"telemetry_last_day": today})
    return True


def schedule(delay: float = START_DELAY) -> None:
    """Fire one heartbeat in the background after startup settles."""
    if not enabled():
        return

    def worker() -> None:
        send()

    timer = threading.Timer(delay, worker)
    timer.daemon = True
    timer.start()
