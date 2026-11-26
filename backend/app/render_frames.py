"""Frame-by-frame export (§5.4.2).

The old path recorded a screen: Playwright's screencast encoded VP9 in
realtime, then ffmpeg re-encoded to x264. Two lossy passes, frame drops
whenever the machine was busy, and a set of calibration hacks to re-time the
result.

This path asks the page to *be* at time `t`, screenshots it, and pipes the PNGs
straight into one x264 pass with the original audio. A frame can only depend on
`t`, so two exports of the same song are byte-identical, and the render no
longer competes with playback for the clock.

Parallelism: the timeline is cut into N contiguous ranges, each rendered by its
own page, then concatenated. `cpu / 2` capped at 4 by default, and it drops to
1 while a `cpu` job (whisper) is running, because both are CPU-bound.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
from pathlib import Path

from app import binaries, export

FPS = export.FPS
DEFAULT_PAGES = 3
MAX_PAGES = 4


def page_count(requested: int | None = None) -> int:
    """How many pages to render with, honouring the setting and load."""
    if requested and requested > 0:
        n = requested
    else:
        n = min(MAX_PAGES, max(1, (os.cpu_count() or 2) // 2))
    n = max(1, min(MAX_PAGES, n))
    # whisper and frame rendering both want every core; one at a time
    from app import jobs

    if jobs.list_jobs(active_only=True):
        n = 1
    return n


def render_segment(base_url: str, song: str, preset_name: str,
                   start: float, end: float, out: Path,
                   progress=None, extra_query: str = "") -> Path:
    """Render `[start, end)` of the song into a silent H.264 clip."""
    from playwright.sync_api import sync_playwright

    size = export.preset(preset_name)
    width = size["width"] * size["scale"]
    height = size["height"] * size["scale"]
    frames = max(1, int(round((end - start) * FPS)))
    out.parent.mkdir(parents=True, exist_ok=True)
    url = (f"{base_url}/?song={export.quote(song, safe='')}&render=1"
           + extra_query)

    with sync_playwright() as pw:
        exe, err = None, ""
        for cand in export._chrome_candidates(pw):
            try:
                browser = pw.chromium.launch(executable_path=cand,
                                             args=export._LAUNCH_ARGS)
                exe = cand
                break
            except Exception as e:  # noqa: BLE001
                err = str(e)[:200]
        if exe is None:
            raise RuntimeError("没有能启动的 Chromium 浏览器:" + (err or "未找到候选"))

        ctx = browser.new_context(
            viewport={"width": size["width"], "height": size["height"]},
            device_scale_factor=size["scale"],
        )
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_selector(".stage", timeout=30_000)
        # the stage publishes `__utaReady` once the virtual clock is installed
        page.wait_for_function(
            "() => window.__utaReady === true", timeout=30_000)
        # a first paint so fonts/背景 are settled before the first frame
        page.evaluate("(t) => window.__utaSeek.seek(t)", start)
        page.wait_for_timeout(150)

        cdp = ctx.new_cdp_session(page)
        encoder = _start_encoder(out, width, height)
        try:
            for i in range(frames):
                t = start + i / FPS
                page.evaluate("(t) => window.__utaSeek.seek(t)", t)
                # let the DOM settle: the seek only changes React state
                page.wait_for_timeout(1)
                shot = cdp.send("Page.captureScreenshot", {
                    "format": "jpeg", "quality": 95,
                    "captureBeyondViewport": False,
                })
                encoder.stdin.write(_b64(shot["data"]))
                if progress and i % 30 == 0:
                    progress(i / frames, f"渲染 {i}/{frames} 帧")
        finally:
            encoder.stdin.close()
            code = encoder.wait()
        ctx.close()
        browser.close()

    if code != 0:
        raise RuntimeError("ffmpeg 编码失败(逐帧渲染)")
    return out


def _b64(data: str) -> bytes:
    import base64

    return base64.b64decode(data)


def _start_encoder(out: Path, width: int, height: int) -> subprocess.Popen:
    """One x264 pass, JPEG frames on stdin.

    Video only: each parallel page muxes its own silent clip, and the audio is
    added once at concat time so a split render still has a continuous track.
    """
    cmd = [binaries.ffmpeg(), "-y", "-v", "error",
           "-f", "image2pipe", "-framerate", str(FPS), "-i", "-",
           "-an", "-r", str(FPS), "-c:v", "libx264", "-preset", "medium",
           "-crf", "18", "-pix_fmt", "yuv420p",
           "-vf", f"scale={width}:{height}",
           "-movflags", "+faststart", str(out)]
    return binaries.popen(cmd, stdin=subprocess.PIPE,
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)


def render(base_url: str, song: str, audio: Path | None, out: Path,
           duration: float, progress=None, extra_query: str = "",
           preset_name: str = export.DEFAULT_PRESET,
           clip_start: float = 0.0,
           pages: int | None = None) -> Path:
    """Render the whole clip, split across pages, then mux the audio once."""
    p = progress or (lambda frac, msg: None)
    n = page_count(pages)
    span = duration / n
    work = Path(tempfile.mkdtemp(prefix="utaframes_"))
    try:
        parts: list[Path] = []
        if n == 1:
            part = work / "part-0.mp4"
            render_segment(base_url, song, preset_name, clip_start,
                           clip_start + duration, part,
                           lambda f, m: p(0.05 + 0.85 * f, m), extra_query)
            parts.append(part)
        else:
            errors: list[str] = []

            def one(i: int) -> None:
                try:
                    a = clip_start + i * span
                    b = a + span if i < n - 1 else clip_start + duration
                    part = work / f"part-{i}.mp4"
                    render_segment(base_url, song, preset_name, a, b, part,
                                   None, extra_query)
                    parts.append(part)
                except Exception as e:  # noqa: BLE001
                    errors.append(str(e))

            threads = [threading.Thread(target=one, args=(i,)) for i in range(n)]
            for t in threads:
                t.start()
            while any(t.is_alive() for t in threads):
                if errors:
                    break
                done = sum(1 for t in threads if not t.is_alive())
                p(0.05 + 0.8 * done / n, f"渲染 {done}/{n} 段")
                threading.Event().wait(0.4)
            for t in threads:
                t.join()
            if errors:
                raise RuntimeError(errors[0])
            parts.sort(key=lambda f: int(f.stem.split("-")[1]))

        if not parts or any(not f.exists() for f in parts):
            raise RuntimeError("逐帧渲染没有产出视频")

        p(0.9, "合并并混入音频…")
        _concat(parts, audio, out, clip_start, duration)
        if not out.exists() or not export._has_video(out):
            raise RuntimeError("合成的成片没有画面")
        p(0.99, "完成")
        return out
    finally:
        import shutil

        shutil.rmtree(work, ignore_errors=True)


def _concat(parts: list[Path], audio: Path | None, out: Path,
            clip_start: float, duration: float) -> None:
    list_file = parts[0].parent / "parts.txt"
    list_file.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in parts) + "\n",
        encoding="utf-8")
    cmd = [binaries.ffmpeg(), "-y", "-v", "error",
           "-f", "concat", "-safe", "0", "-i", str(list_file)]
    if audio is not None and audio.exists():
        if clip_start > 0.02:
            cmd += ["-ss", f"{clip_start:.3f}"]
        cmd += ["-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-t", f"{duration:.3f}"]
    else:
        cmd += ["-map", "0:v:0", "-c:v", "copy", "-an",
                "-t", f"{duration:.3f}"]
    cmd += ["-movflags", "+faststart", str(out)]
    binaries.run(cmd, check=True, capture_output=True)
