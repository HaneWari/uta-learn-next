"""Check an exported MP4 against its source audio.

Two independent questions:

1. **Is the audio track still where the source says it is?** Cross-correlating a
   slice of the exported audio with the same slice of the source catches a shift
   or a stretch introduced by muxing/encoding.
2. **Does the picture agree with the audio?** The stage paints a progress bar
   into every frame, and that bar is driven by `audio.currentTime`, so comparing
   the bar reading to the frame's position in the file measures A/V sync.

Question 1 is the one the progress-bar method cannot answer on its own: if the
muxed audio were shifted, bar and picture would still agree with each other
while both drifted against the sound.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

BAR_LO, BAR_HI = 0.035, 0.968
SR = 16000


def decode_audio(path: Path, ss: float, dur: float) -> np.ndarray:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{ss:.3f}", "-t", f"{dur:.3f}",
         "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(out, dtype="<i2").astype(np.float64)


def best_offset(a: np.ndarray, b: np.ndarray, max_lag: float = 2.0) -> tuple[float, float]:
    """(lag_seconds, peak_correlation) aligning b onto a."""
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    if n < SR:
        return 0.0, 0.0
    a = a - a.mean()
    b = b - b.mean()
    size = 1 << int(np.ceil(np.log2(2 * n)))
    corr = np.fft.irfft(np.fft.rfft(a, size) * np.conj(np.fft.rfft(b, size)), size)
    half = int(max_lag * SR)
    corr = np.concatenate([corr[-half:], corr[:half + 1]])
    lags = np.arange(-half, half + 1)
    i = int(np.argmax(np.abs(corr)))
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
    return float(lags[i]) / SR, float(corr[i] / denom)


def grab(video: Path, t: float, out: Path) -> np.ndarray:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}",
         "-i", str(video), "-frames:v", "1", str(out)],
        check=True, capture_output=True,
    )
    return np.asarray(Image.open(out).convert("RGB")).astype("int16")


def bar_played(img: np.ndarray, duration: float) -> float | None:
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--audio", help="原始音频；给了才会做音频对源检查")
    ap.add_argument("--samples", type=int, default=9)
    args = ap.parse_args()

    video = Path(args.video)
    if not video.exists():
        print(f"找不到：{video}", file=sys.stderr)
        return 2

    info = json.loads(subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", str(video)],
        capture_output=True, text=True).stdout)
    total = float(info["format"]["duration"])
    print(f"成片 {total:.2f}s")

    worst = 0.0
    if args.audio:
        audio = Path(args.audio)
        if not audio.exists():
            print(f"找不到音频：{audio}", file=sys.stderr)
            return 2
        print("\n[音频对源] 互相关（正数=成片音频比源晚）")
        for frac in (0.1, 0.35, 0.6, 0.85):
            t = total * frac
            seg = min(8.0, total - t - 0.2)
            if seg <= 1.0:
                continue
            a = decode_audio(video, t, seg)
            b = decode_audio(audio, t, seg)
            lag, peak = best_offset(a, b)
            worst = max(worst, abs(lag))
            print(f"  t={t:7.2f}s  偏移 {lag:+.3f}s  相关 {peak:.3f}")

    print("\n[画面对音频] 进度条读数 − 帧位置")
    work = Path(tempfile.mkdtemp(prefix="utasync_"))
    rows = []
    for i in range(args.samples):
        frac = 0.05 + 0.9 * i / max(1, args.samples - 1)
        t = total * frac
        played = bar_played(grab(video, t, work / f"g{i}.png"), total)
        if played is None:
            print(f"  t={t:7.2f}s  读不到（可能被谢幕卡遮住）")
            continue
        rows.append((t, played - t))
        print(f"  t={t:7.2f}s  偏差 {played - t:+.3f}s")

    if len(rows) >= 3:
        ts = np.array([r[0] for r in rows])
        ds = np.array([r[1] for r in rows])
        A = np.vstack([np.ones_like(ts), ts]).T
        a0, b0 = np.linalg.lstsq(A, ds, rcond=None)[0]
        print(f"\n拟合：偏差 = {a0:+.2f}s + {b0:+.5f} × t")
        print(f"  起点 {a0:+.2f}s → 末端 {a0 + b0 * total:+.2f}s")
        if abs(b0) > 0.002:
            print(f"  → 线性漂移：整段被缩放约 {b0 * 100:+.2f}%")
        elif abs(a0) > 0.12:
            print("  → 常量偏移")
        else:
            print("  → 对齐")

    shutil.rmtree(work, ignore_errors=True)
    if args.audio:
        print(f"\n音频最大偏移 {worst:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
