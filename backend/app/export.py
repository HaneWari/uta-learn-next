"""Render a dataset's stage to an MP4.

Two things make the output line up with its audio:

* The recording starts when the browser context is created, which is *before*
  the page has loaded. Whatever time passes until playback begins would show up
  as a static prefix — that is the "first ten seconds are frozen" bug. The
  offset between context creation and `play()` is measured and trimmed off.
* ffmpeg re-times the result to a fixed 60 fps, so the deliverable has a stable
  frame rate regardless of what the compositor produced.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

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

    Numbers come from the recording path's measured throughput: ~55 ms per
    1080p frame and ~150 ms per 4K frame, divided across the parallel pages.
    It is an estimate and the dialog says so — being 30% off is fine, being
    silent for ten minutes is not.
    """
    per_frame = 0.150 if (preset_name or DEFAULT_PRESET) == "4k" else 0.055
    frames = max(1.0, duration) * FPS
    return int(frames * per_frame / max(1, pages))

# The recorder sometimes stops a little before the requested length (frame drops,
# a slow first paint). The video track is padded by cloning its last frame for up
# to this many seconds so it can never end before the audio does — that gap was
# the "last few seconds have no picture" half of the duration bug.
PAD_MAX = 12.0

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
    # browser most users already have. Anything with a Chromium core works —
    # Playwright's record_video only needs CDP, not Google Chrome specifically —
    # so Edge (bundled with Windows), Brave, Vivaldi, 360, QQ, Sogou etc. all
    # count as a working export browser.
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


# Flags every launch uses — also the ones render() passes, so a candidate that
# probes green here is guaranteed to come up in the real recorder too.
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
    runs (64-bit exe on ARM, killed DLL, blocked by policy, partial install…).

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


def probe_record_video(exe: str, timeout_ms: int = _PROBE_TIMEOUT) -> tuple[bool, str]:
    """Launch the chosen browser and open a recording context — the *real*
    requirement for export. A browser that starts but can't record (missing
    playwright ffmpeg-*, broken codec support) would launch green yet still
    fail mid-export, so it gets probed too.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa: BLE001
        return False, f"playwright 不可用：{e}"
    work = Path(tempfile.mkdtemp(prefix="utaprobe_"))
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=exe, timeout=timeout_ms, args=_LAUNCH_ARGS)
            ctx = browser.new_context(
                viewport={"width": 64, "height": 64},
                record_video_dir=str(work),
                record_video_size={"width": 64, "height": 64})
            ctx.new_page().goto("about:blank")
            ctx.close()          # closing flushes + exercises the recorder
            browser.close()
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:300]
    finally:
        import shutil as _sh
        _sh.rmtree(work, ignore_errors=True)


def env_check() -> dict:
    """Detailed environment diagnosis for the export feature.

      ok            — a Chromium browser launched fine, export will work
      no_playwright — the python package itself is missing → offer pip fix
      no_browser    — playwright is there but nothing launches → offer the
                      bundled-Chromium extension pack
      no_ffmpeg     — browser is fine but the mux tool is missing

    `no_recorder` is no longer a failure state. The frame renderer drives CDP
    and pipes screenshots into ffmpeg, so Playwright's own video/ffmpeg
    component is only needed by 兼容模式 — and telling a user "视频录制组件错误"
    while the picture path is healthy was one of the failure classes §5.4.2 set
    out to delete. The probe is still reported, as `compat_ready`.
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

    record_ok, record_err = (False, "")
    if launch_ok and state == "ok":
        record_ok, record_err = probe_record_video(exe)

    return {
        "ok": state == "ok",
        "state": state,
        "checks": {
            "playwright": has_playwright,
            "browser_path": exe,
            "bundled_chromium": _has_bundled_chromium(),
            "browser_launch": launch_ok,
            "launch_error": launch_err,
            "record_video": record_ok,
            "record_error": record_err,
            "ffmpeg": has_ffmpeg,
            "candidates": _chrome_candidates() if has_playwright else [],
            "compat_ready": bool(launch_ok and record_ok and has_ffmpeg),
        },
    }


# --------------------------------------------------------------------------- #
# self-calibration: the progress bar is a clock painted into every frame
# --------------------------------------------------------------------------- #
# Calibrated against known seek positions: with 0.963 the reading ran
# ~0.55% high at the end of a song (a +1.2s phantom drift), which made the
# auto-correction chase an error that was not there. 0.968 is the value that
# makes the bar agree with currentTime across the whole range.
BAR_LO, BAR_HI = 0.035, 0.968


def _grab(video: Path, t: float, out: Path) -> object:
    import numpy as np
    from PIL import Image

    binaries.run(
        [binaries.ffmpeg(), "-y", "-loglevel", "error", "-ss", f"{t:.3f}",
         "-i", str(video), "-frames:v", "1", str(out)],
        check=True, capture_output=True,
    )
    return np.asarray(Image.open(out).convert("RGB")).astype("int16")


def _bar_played(img, duration: float) -> float | None:
    """Seconds of playback encoded by the progress bar in this frame."""
    import numpy as np

    h, w, _ = img.shape
    for y in range(h - 1, h - 80, -1):
        row = img[y]
        r, g, b = row[:, 0], row[:, 1], row[:, 2]
        orange = (r > 190) & (g > 70) & (g < 175) & (b < 110)
        idx = np.where(orange)[0]
        if len(idx) > 60:
            ratio = float(idx.max()) / w
            pct = max(0.0, min(1.0, (ratio - BAR_LO) / (BAR_HI - BAR_LO)))
            return pct * duration
    return None


def measure_offset(video: Path, duration: float, work: Path,
                   base: float = 0.0) -> float | None:
    """Median (content time - frame time) in seconds, or None if unreadable.

    `base` is where the recorded clip starts in the song: the progress bar
    reads the *absolute* playhead, so a clip that begins at 1:30 would look
    like a +90s drift without it.
    """
    import numpy as np

    span = max(1.0, duration)
    samples = [span * f for f in (0.12, 0.3, 0.5, 0.7, 0.88)]
    deltas = []
    for t in samples:
        try:
            played = _bar_played(_grab(video, t, work / f"m{t:.2f}.png"), duration)
        except Exception:  # noqa: BLE001
            continue
        if played is not None:
            deltas.append(played - base - t)
    return float(np.median(deltas)) if deltas else None


def _probe_duration(video: Path) -> float:
    """Container duration in seconds (via the shared ffmpeg-only probe)."""
    return binaries.probe_duration(video)


def _has_video(path: Path) -> bool:
    """True when the container really carries a video stream.

    ffmpeg happily writes an audio-only MP4 when the filter chain produced
    zero frames, which is how a bad calibration pass could turn a
    "successful" export into a file with no picture at all.
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


def _mux(raw: Path, audio: Path | None, out: Path, duration: float,
         skip: float, scale: float = 1.0, audio_offset: float = 0.0) -> None:
    """Trim, re-time and mux.

    `scale` corrects a real defect in the recorder: the WebM it produces is not
    guaranteed to span the wall-clock time it actually covered. Measured on a
    221.6s song, the picture ran ~1.4% long, so every later lyric landed
    progressively later than the audio (a +2.7s error by the end of the song).
    Scaling the presentation timestamps by (real elapsed / recorded span) puts
    the picture back on the audio's clock.
    """
    cmd = [binaries.ffmpeg(), "-y", "-v", "error"]
    if skip > 0.02:
        cmd += ["-ss", f"{skip:.3f}"]
    cmd += ["-i", str(raw)]
    if audio is not None and audio.exists():
        if audio_offset > 0.02:
            # a clip export starts mid-song: cut the audio at the same instant
            cmd += ["-ss", f"{audio_offset:.3f}"]
        cmd += ["-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
                "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-map", "0:v:0", "-an"]
    vf = ""
    if abs(scale - 1.0) > 0.0005:
        # setpts must run before fps=, so the resampler sees corrected times
        vf += f"setpts={scale:.6f}*PTS,"
    vf += f"fps={FPS},tpad=stop_mode=clone:stop_duration={PAD_MAX:.0f}"
    cmd += ["-vf", vf,
            "-r", str(FPS),
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    binaries.run(cmd, check=True, capture_output=True)


def render(base_url: str, song: str, audio: Path | None, out: Path,
           duration: float, progress=None, extra_query: str = "",
           preset_name: str = DEFAULT_PRESET,
           clip_start: float = 0.0) -> Path:
    """Record `?song=<song>&render=1` and write `out` as 60 fps H.264 + AAC.

    `clip_start` + `duration` describe the slice to record: playback begins at
    `clip_start`, the audio is cut at the same instant, and the progress-bar
    calibration is offset by it.
    """
    from playwright.sync_api import sync_playwright

    p = progress or (lambda frac, msg: None)
    # don't gate on available()/env_check here: they re-run pick_browser and a
    # flaky or slow probe can disagree with the launch loop right below and
    # report "导出不可用" even when a browser would come up. The launch loop
    # is the authoritative check — it tries every candidate for real.

    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="utaexport_"))
    size = preset(preset_name)
    # Quote the name: a title like "Q&A" or "#1" (both survive slugify) would
    # otherwise become a query separator or a fragment and the recorder would
    # open the wrong song — or an empty stage.
    url = f"{base_url}/?song={quote(song, safe='')}&render=1{extra_query}"

    try:
        p(0.02, "启动浏览器…")
        with sync_playwright() as pw:
            # launch the first candidate that actually comes up — same pick as
            # the pre-flight probe, so a broken playwright cache can't mask a
            # healthy system browser sitting behind it
            exe, err = (None, "")
            for cand in _chrome_candidates(pw):
                try:
                    exe, err = cand, ""
                    browser = pw.chromium.launch(
                        executable_path=cand, args=_LAUNCH_ARGS)
                    break
                except Exception as e:  # noqa: BLE001
                    err = str(e)[:300]
                    exe = None
            if exe is None:
                raise RuntimeError(
                    "没有能启动的 Chromium 浏览器：" + (err or "未找到候选"))
            ctx = browser.new_context(
                viewport={"width": size["width"], "height": size["height"]},
                device_scale_factor=size["scale"],
                record_video_dir=str(work),
                record_video_size={"width": size["width"], "height": size["height"]},
            )
            # recording starts here — everything until play() is dead air
            t_record = time.monotonic()

            page = ctx.new_page()
            p(0.05, "载入舞台…")
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_selector(".stage", timeout=30_000)
            # wait for the audio element to actually be able to play
            page.wait_for_function(
                """() => {
                    const a = document.querySelector('audio');
                    return !a || a.readyState >= 2;
                }""",
                timeout=30_000,
            )
            page.wait_for_timeout(300)

            p(0.08, "开始播放…")
            page.evaluate(
                """(start) => {
                    const a = document.querySelector('audio');
                    if (a) { a.currentTime = start; a.play(); }
                }""",
                clip_start,
            )
            t_play = time.monotonic()
            # the frozen prefix in the recording
            offset = max(0.0, t_play - t_record)

            p(0.10, "录制中…")
            # Follow the audio instead of the wall clock: a slow machine can fall
            # behind real time, and stopping on a timer then cut the tail off.
            waited = 0.0
            cap = duration + 20.0
            while waited < cap:
                page.wait_for_timeout(500)
                waited += 0.5
                done = page.evaluate(
                    """(end) => {
                        const a = document.querySelector('audio');
                        if (!a) return true;
                        return a.ended || a.currentTime >= end;
                    }""",
                    clip_start + duration - 0.1,
                )
                p(min(0.88, 0.10 + 0.78 * min(waited, duration) / max(1.0, duration)),
                  "录制中…")
                if done:
                    # let the final frame land before closing the context
                    page.wait_for_timeout(400)
                    break

            video = page.video
            raw = Path(video.path()) if video else None
            t_end = time.monotonic()
            ctx.close()
            browser.close()

        if raw is None or not raw.exists():
            raise RuntimeError("浏览器没有产出录制文件")

        p(0.90, "合成音视频…")
        # Trim the dead prefix, then re-time to a constant 60 fps.
        skip = offset
        # How long the picture *should* be, measured by the clock rather than by
        # trusting the recorder's timestamps.
        elapsed = max(0.1, t_end - t_play)
        raw_span = _probe_duration(raw)
        scale = 1.0
        if raw_span and raw_span - skip > 1.0:
            scale = elapsed / (raw_span - skip)
            # a sane recorder is within a few percent; anything outside that is a
            # bad probe, not a real stretch
            if not (0.90 <= scale <= 1.10):
                scale = 1.0
        _mux(raw, audio, out, duration, skip, scale, clip_start)

        if not out.exists() or out.stat().st_size < 1024:
            raise RuntimeError("ffmpeg 没有生成有效的视频")
        if not _has_video(out):
            raise RuntimeError(
                "导出结果只有音轨，没有画面。请重试；若仍失败，"
                "可在设置 → 导出里打开兼容模式。")

        # The wall-clock offset is only an estimate: the recorder's first frame
        # does not land exactly at new_context(). Read the progress bar back out
        # of the result and correct once, so picture and audio really agree.
        p(0.95, "校准音画对齐…")
        residual = measure_offset(out, duration, work, clip_start)
        if residual is not None and abs(residual) > 0.12:
            # residual > 0 means the picture is ahead of the audio, so trim
            # less of the raw recording (not more).
            corrected = max(0.0, skip - residual)
            # A reading can be nonsense when another orange element sits on the
            # bottom row (the portrait layout puts the cards there). Trimming
            # past the end of the recording would leave zero frames, so only
            # accept a correction that still keeps the clip.
            if raw_span and corrected < raw_span - 0.5:
                p(0.97, f"重新对齐(偏差 {residual:+.2f}s)...")
                _mux(raw, audio, out, duration, corrected, scale, clip_start)
                if _has_video(out):
                    residual = measure_offset(out, duration, work, clip_start)
                    skip = corrected
                else:
                    # never ship audio-only: fall back to the first mux
                    _mux(raw, audio, out, duration, skip, scale, clip_start)
                    residual = None
            else:
                p(0.97, "跳过音画微调（读取结果不可信）")

        p(0.99, "完成" + (f"（残余偏差 {residual:+.2f}s）" if residual is not None else ""))
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)
