"""Shared settings for the frame-by-frame video exporter.

`render_frames.py` is the only renderer. It asks the page to be at time `t`,
screenshots that frame and pipes the PNGs into one x264 pass with the original
audio, so a frame can only depend on `t` and the result is deterministic.

This module owns the presets, the browser resolver and the pre-flight probe
that decides whether an export can start at all.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import binaries

W, H = 1920, 1080
FPS = 60

# Three presets, all fixed 60 fps. 4K reuses the 1080p layout with
# `device_scale_factor=2` instead of a second stylesheet — same arrangement,
# twice the pixels, nothing extra to maintain.
PRESETS: dict[str, dict] = {
    "landscape": {"label": "横屏 1080p", "width": 1920, "height": 1080, "scale": 1},
    "portrait": {"label": "竖屏 1080p", "width": 1080, "height": 1920, "scale": 1},
    "4k": {"label": "4K 横屏", "width": 1920, "height": 1080, "scale": 2},
}
DEFAULT_PRESET = "landscape"


def preset(name: str | None) -> dict:
    return PRESETS.get(name or DEFAULT_PRESET, PRESETS[DEFAULT_PRESET])


def estimate_seconds(duration: float, preset_name: str | None = None,
                     pages: int = 3) -> int:
    """Rough wall-clock estimate for the export dialog.

    Numbers come from the frame renderer's measured throughput: ~55 ms per
    1080p frame and ~150 ms per 4K frame, divided across the parallel pages.
    It is an estimate and the dialog says so — being 30% off is fine, being
    silent for ten minutes is not.
    """
    per_frame = 0.150 if (preset_name or DEFAULT_PRESET) == "4k" else 0.055
    frames = max(1.0, duration) * FPS
    return int(frames * per_frame / max(1, pages))


# An explicit browser beats anything we could guess; otherwise Playwright's own
# download is preferred, then a system Chrome.
CHROME_ENV = "UTALEARN_CHROME"


def _chrome_candidates(pw=None) -> list[str]:
    """Every Chromium executable we could try, best guess first.

    `pw` must be passed when a Playwright context is already open: starting a
    second sync context inside it would raise.

    The order encodes preference (explicit override → Playwright's pinned build
    → bundled extension pack → cache → system installs → PATH), but *existence*
    is all that's checked here. Which one actually launches is decided by
    probing, because a path that exists is no proof it runs — a partial
    `playwright install` leaves a real-looking chrome.exe that fails to spawn,
    and that one bad candidate must not mask a working system Chrome behind it.
    """
    candidates: list[str] = []

    override = os.environ.get(CHROME_ENV)
    if override and Path(override).exists():
        candidates.append(override)

    try:
        if pw is not None:
            candidates.append(pw.chromium.executable_path)
        else:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as own:
                candidates.append(own.chromium.executable_path)
    except Exception:  # noqa: BLE001
        pass

    # Any chromium build already on disk, newest revision first. The portable
    # build ships one next to the app (`browsers/`), so that folder is checked
    # before the per-user cache — no installation, no download.
    roots: list[Path] = []
    bundled = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if bundled:
        roots.append(Path(bundled))
    roots.append(Path(__file__).resolve().parents[2] / "browsers")
    roots.append(Path.home() / "AppData/Local/ms-playwright")
    roots.append(Path.home() / ".cache/ms-playwright")

    for root in roots:
        if not root.is_dir():
            continue
        for b in sorted(root.glob("chromium-*"), reverse=True):
            for rel in ("chrome-win64/chrome.exe", "chrome-linux/chrome",
                        "chrome-mac/Chromium.app/Contents/MacOS/Chromium"):
                p = b / rel
                if p.exists():
                    candidates.append(str(p))

    # A normal browser install is *not* on PATH, so `which` alone misses the
    # browser most users already have. Frame capture only needs CDP, not Google
    # Chrome specifically, so Edge (bundled with Windows), Brave, Vivaldi, 360,
    # QQ, Sogou etc. all count as a working export browser.
    for guess in (
        r"C:/Program Files/Google/Chrome/Application/chrome.exe",
        r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
        r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        r"C:/Program Files/Microsoft/Edge/Application/msedge.exe",
        r"C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe",
        r"C:/Program Files (x86)/BraveSoftware/Brave-Browser/Application/brave.exe",
        os.path.expandvars(r"%LOCALAPPDATA%/Programs/Vivaldi/Application/vivaldi.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%/360Chrome/Chrome/Application/360chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%/Tencent/QQBrowser/qqbrowser.exe"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/usr/bin/google-chrome",
        "/usr/bin/microsoft-edge",
        "/usr/bin/brave-browser",
        "/usr/bin/chromium",
    ):
        if Path(guess).exists():
            candidates.append(guess)

    for name in (
        "chrome", "google-chrome", "chromium",
        "msedge", "microsoft-edge", "edge",
        "brave", "brave-browser", "vivaldi",
    ):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    # de-dup preserving order — several of the guesses resolve to one install
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        key = os.path.normcase(c) if c else c
        if c and key not in seen and Path(c).exists():
            seen.add(key)
            out.append(c)
    return out


def _chrome(pw=None) -> str | None:
    """First existing candidate — kept for callers that just need *a* path."""
    c = _chrome_candidates(pw)
    return c[0] if c else None


def _has_bundled_chromium() -> bool:
    """True when an extension-pack Chromium sits next to the app (`browsers/`)."""
    root = Path(__file__).resolve().parents[2] / "browsers"
    if not root.is_dir():
        return False
    for b in root.glob("chromium-*"):
        for rel in ("chrome-win64/chrome.exe", "chrome-linux/chrome",
                    "chrome-mac/Chromium.app/Contents/MacOS/Chromium"):
            if (b / rel).exists():
                return True
    return False


# Flags every launch uses — render_frames passes the same list, so a candidate
# that probes green here is guaranteed to come up in the real render too.
_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-gpu",
    "--autoplay-policy=no-user-gesture-required",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-features=CalculateNativeWinOcclusion",
    "--hide-scrollbars",
    "--mute-audio",
]


# a cold browser + an overzealous AV can take a while; 15 s was too tight and
# turned real, working installs into "no_browser" false negatives
_PROBE_TIMEOUT = 30000


def probe_browser(exe: str, timeout_ms: int = _PROBE_TIMEOUT, pw=None) -> tuple[bool, str]:
    """Actually launch the candidate once — a path that exists is not proof it
    runs (64-bit exe on ARM, killed DLL, blocked by policy, partial install...).

    `pw` lets the caller reuse an open Playwright context: spinning up one
    `sync_playwright()` per candidate is wasteful when probing a list.
    """
    def _try(p):
        browser = p.chromium.launch(
            executable_path=exe, timeout=timeout_ms, args=_LAUNCH_ARGS)
        browser.new_context().new_page().goto("about:blank")
        browser.close()
        return True

    try:
        if pw is not None:
            _try(pw)
        else:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as own:
                _try(own)
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:300]


def pick_browser(timeout_ms: int = _PROBE_TIMEOUT) -> tuple[str | None, str]:
    """First candidate that actually launches, else (None, last error).

    One sync_playwright context serves the whole scan so a broken first
    candidate doesn't cost a fresh driver per try.
    """
    candidates = _chrome_candidates()
    if not candidates:
        return None, "没有找到任何 Chromium 候选路径"
    err = ""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            for exe in candidates:
                ok, err = probe_browser(exe, timeout_ms=timeout_ms, pw=pw)
                if ok:
                    return exe, ""
    except Exception as e:  # noqa: BLE001
        err = str(e)[:300]
    return None, err or "没有候选浏览器能启动"


def env_check() -> dict:
    """Detailed environment diagnosis for the export feature.

      ok            — a Chromium browser launched fine, export will work
      no_playwright — the python package itself is missing → offer pip fix
      no_browser    — playwright is there but nothing launches → offer the
                      bundled-Chromium extension pack
      no_ffmpeg     — browser is fine but the mux tool is missing

    The frame renderer drives CDP and pipes screenshots into ffmpeg, so
    Playwright's own video/ffmpeg component is not part of the requirement.
    """
    try:
        import playwright  # noqa: F401
        has_playwright = True
    except Exception:  # noqa: BLE001
        has_playwright = False

    exe, launch_err = (None, "")
    if has_playwright:
        exe, launch_err = pick_browser()
    launch_ok = exe is not None

    has_ffmpeg = binaries.find("ffmpeg") is not None

    if not has_playwright:
        state = "no_playwright"
    elif not launch_ok:
        state = "no_browser"
    elif not has_ffmpeg:
        state = "no_ffmpeg"
    else:
        state = "ok"

    return {
        "ok": state == "ok",
        "state": state,
        "checks": {
            "playwright": has_playwright,
            "browser_path": exe,
            "bundled_chromium": _has_bundled_chromium(),
            "browser_launch": launch_ok,
            "launch_error": launch_err,
            "ffmpeg": has_ffmpeg,
            "candidates": _chrome_candidates() if has_playwright else [],
        },
    }


def _has_video(path: Path) -> bool:
    """True when the container really carries a video stream.

    ffmpeg happily writes an audio-only MP4 when the filter chain produced
    zero frames, so a "successful" export would otherwise be a file with no
    picture at all.
    """
    try:
        out = binaries.run(
            [binaries.ffmpeg(), "-hide_banner", "-i", str(path)],
            capture_output=True, text=True, check=False,
        ).stderr
    except (OSError, subprocess.SubprocessError):
        return False
    # `Stream #0:0 ...: Video:` appears only when a video stream exists
    return "Video:" in out
