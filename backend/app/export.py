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

W, H = 1920, 1080
FPS = 60

# The recorder sometimes stops a little before the requested length (frame drops,
# a slow first paint). The video track is padded by cloning its last frame for up
# to this many seconds so it can never end before the audio does — that gap was
# the "last few seconds have no picture" half of the duration bug.
PAD_MAX = 12.0

# An explicit browser beats anything we could guess; otherwise Playwright's own
# download is preferred, then a system Chrome.
CHROME_ENV = "UTALEARN_CHROME"


def _chrome(pw=None) -> str | None:
    """Resolve a Chromium executable.

    `pw` must be passed when a Playwright context is already open: starting a
    second sync context inside it would raise.

    Playwright's own `executable_path` is not enough here. The Python package
    pins one browser revision, and the machine often has a different one
    installed (another Playwright version, or a partial download), so the pinned
    path can simply not exist. Fall back to scanning the browser cache for any
    usable build before giving up.
    """
    override = os.environ.get(CHROME_ENV)
    if override and Path(override).exists():
        return override

    candidates: list[str] = []
    try:
        if pw is not None:
            candidates.append(pw.chromium.executable_path)
        else:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as own:
                candidates.append(own.chromium.executable_path)
    except Exception:  # noqa: BLE001
        pass

    # any chromium build already in the cache, newest revision first
    cache = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")) if os.environ.get(
        "PLAYWRIGHT_BROWSERS_PATH") else Path.home() / "AppData/Local/ms-playwright"
    if not cache.is_dir():
        cache = Path.home() / ".cache/ms-playwright"
    if cache.is_dir():
        builds = sorted(cache.glob("chromium-*"), reverse=True)
        for b in builds:
            for rel in ("chrome-win64/chrome.exe", "chrome-linux/chrome",
                        "chrome-mac/Chromium.app/Contents/MacOS/Chromium"):
                p = b / rel
                if p.exists():
                    candidates.append(str(p))

    for name in ("chrome", "google-chrome", "chromium"):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


def available() -> tuple[bool, str]:
    """(can export, why not)"""
    try:
        import playwright  # noqa: F401
    except Exception:  # noqa: BLE001
        return False, "没有安装 playwright（python -m pip install playwright）"
    if _chrome() is None:
        return False, "没找到 Chrome/Chromium"
    if shutil.which("ffmpeg") is None:
        return False, "没找到 ffmpeg"
    return True, ""



# --------------------------------------------------------------------------- #
# self-calibration: the progress bar is a clock painted into every frame
# --------------------------------------------------------------------------- #
# Calibrated against known seek positions: with 0.963 the reading ran
# ~0.55% high at the end of a song (a +1.2s phantom drift), which made the
# auto-correction chase an error that was not there. 0.968 is the value that
# makes the bar agree with currentTime across the whole range.
BAR_LO, BAR_HI = 0.035, 0.968


def _grab(video: Path, t: float, out: Path) -> "object":
    import numpy as np
    from PIL import Image

    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}",
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


def measure_offset(video: Path, duration: float, work: Path) -> float | None:
    """Median (content time - frame time) in seconds, or None if unreadable."""
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
            deltas.append(played - t)
    return float(np.median(deltas)) if deltas else None


def _probe_duration(video: Path) -> float:
    """Container duration in seconds, or 0 when ffprobe cannot read it."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(video)],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return float(out)
    except Exception:  # noqa: BLE001
        return 0.0


def _mux(raw: Path, audio: Path | None, out: Path, duration: float,
         skip: float, scale: float = 1.0) -> None:
    """Trim, re-time and mux.

    `scale` corrects a real defect in the recorder: the WebM it produces is not
    guaranteed to span the wall-clock time it actually covered. Measured on a
    221.6s song, the picture ran ~1.4% long, so every later lyric landed
    progressively later than the audio (a +2.7s error by the end of the song).
    Scaling the presentation timestamps by (real elapsed / recorded span) puts
    the picture back on the audio's clock.
    """
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if skip > 0.02:
        cmd += ["-ss", f"{skip:.3f}"]
    cmd += ["-i", str(raw)]
    if audio is not None and audio.exists():
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
    subprocess.run(cmd, check=True, capture_output=True)


def render(base_url: str, song: str, audio: Path | None, out: Path,
           duration: float, progress=None) -> Path:
    """Record `?song=<song>&render=1` and write `out` as 60 fps H.264 + AAC."""
    from playwright.sync_api import sync_playwright

    p = progress or (lambda frac, msg: None)
    ok, why = available()
    if not ok:
        raise RuntimeError(why)

    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="utaexport_"))
    url = f"{base_url}/?song={song}&render=1"

    try:
        p(0.02, "启动浏览器…")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=_chrome(pw),
                args=[
                    "--autoplay-policy=no-user-gesture-required",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-features=CalculateNativeWinOcclusion",
                    "--hide-scrollbars",
                    "--mute-audio",
                ],
            )
            ctx = browser.new_context(
                viewport={"width": W, "height": H},
                device_scale_factor=1,
                record_video_dir=str(work),
                record_video_size={"width": W, "height": H},
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
                """() => {
                    const a = document.querySelector('audio');
                    if (a) { a.currentTime = 0; a.play(); }
                }"""
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
                    """() => {
                        const a = document.querySelector('audio');
                        if (!a) return true;
                        return a.ended || (a.duration && a.currentTime >= a.duration - 0.15);
                    }"""
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
        _mux(raw, audio, out, duration, skip, scale)

        if not out.exists() or out.stat().st_size < 1024:
            raise RuntimeError("ffmpeg 没有生成有效的视频")

        # The wall-clock offset is only an estimate: the recorder's first frame
        # does not land exactly at new_context(). Read the progress bar back out
        # of the result and correct once, so picture and audio really agree.
        p(0.95, "校准音画对齐…")
        residual = measure_offset(out, duration, work)
        if residual is not None and abs(residual) > 0.12:
            # residual > 0 means the picture is ahead of the audio, so trim
            # less of the raw recording (not more).
            corrected = max(0.0, skip - residual)
            p(0.97, f"重新对齐（偏差 {residual:+.2f}s）…")
            _mux(raw, audio, out, duration, corrected, scale)
            residual = measure_offset(out, duration, work)
            skip = corrected

        p(0.99, "完成" + (f"（残余偏差 {residual:+.2f}s）" if residual is not None else ""))
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)
