"""Fallback timing: whisper word anchors + vocal energy segmentation.

Used when no lyric source has the song, or the user prefers to build from their
own audio. The lyrics are the user's (or the source's) text; only the *timing*
is estimated here.

Pipeline
--------
1. Decode the upload to 16 kHz mono PCM with ffmpeg.
2. Transcribe with faster-whisper, keeping word-level timestamps.
3. Align lyric lines to whisper segments with a global monotonic DP, so one bad
   line can never drag the rest of the timeline out of order. Lines whisper
   missed (thick choruses) are laid into the gap between placed neighbours.
4. Inside a line, share the morae across whisper's word spans in proportion to
   their length, then cut each span where the vocal energy changes — this is the
   "energy path": each mora carries one vowel nucleus, so cut points land
   between vowel cores even on legato phrases with no audible onset.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unicodedata
import wave
from pathlib import Path

import numpy as np

from .builder import _prefer_kana_lemma
from .dicts import analyze, enrich, find_grammar, is_content, mora_count

PUNCT_RE = re.compile(r"[\s、。,.!?！？…「」『』()（）・~〜\-—:;\"'’“”]")
JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
MATCH_BONUS = 0.55
HOP = 0.010
WIN = 0.032
MIN_DIST = 0.070
SMOOTH = 3


# --------------------------------------------------------------------------- #
# audio
# --------------------------------------------------------------------------- #
def to_wav(src: str | Path, dst: str | Path | None = None) -> Path:
    """Decode anything ffmpeg reads into 16 kHz mono 16-bit PCM."""
    dst = Path(dst) if dst else Path(tempfile.gettempdir()) / f"utalearn_{os.getpid()}.wav"
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src),
           "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", str(dst)]
    subprocess.run(cmd, check=True, capture_output=True)
    return dst


def probe_duration(src: str | Path) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=nw=1:nk=1", str(src)]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    try:
        return float(out.strip())
    except ValueError:
        return 0.0


def load_wav(path: str | Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if sw != 2:
        raise ValueError("expect 16-bit PCM")
    x = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


# --------------------------------------------------------------------------- #
# energy
# --------------------------------------------------------------------------- #
def _frames(x: np.ndarray, sr: int):
    win = max(1, int(WIN * sr))
    hop = max(1, int(HOP * sr))
    n = 1 + max(0, (len(x) - win) // hop)
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    return x[idx], hop / sr


def _db_curve(x: np.ndarray, sr: int) -> tuple[np.ndarray, float]:
    fr, hop_s = _frames(x, sr)
    rms = np.sqrt(np.mean(fr.astype(np.float64) ** 2, axis=1) + 1e-12)
    db = 20.0 * np.log10(rms + 1e-9)
    return np.convolve(db, np.ones(SMOOTH) / SMOOTH, mode="same"), hop_s


def _even(t0: float, t1: float, n: int) -> list[tuple[float, float]]:
    if n <= 0:
        return []
    step = max(0.02, (t1 - t0) / n)
    out = []
    for i in range(n):
        s = t0 + i * step
        e = s + step if i + 1 < n else t1
        out.append((round(s, 3), round(max(e, s + 0.02), 3)))
    return out


def _dp_segment(energy: np.ndarray, n: int, min_frames: int) -> list[int]:
    """Split a 1-D curve into n contiguous parts of minimal within-part variance.

    Each Japanese mora carries one vowel nucleus, so minimal-variance cut points
    land between vowel cores — which works on legato phrases where there is no
    energy dip to detect as an onset.
    """
    T = len(energy)
    if n <= 1 or T < n * min_frames:
        return [0] + [int(round(T * i / n)) for i in range(1, n)] + [T]

    c1 = np.concatenate([[0.0], np.cumsum(energy)])
    c2 = np.concatenate([[0.0], np.cumsum(energy ** 2)])

    def cost(i: int, j: int) -> float:
        m = j - i
        if m <= 0:
            return 1e18
        s1 = c1[j] - c1[i]
        s2 = c2[j] - c2[i]
        return float(s2 - s1 * s1 / m)

    INF = 1e18
    dp = np.full((n + 1, T + 1), INF)
    prev = np.zeros((n + 1, T + 1), dtype=np.int32)
    dp[0][0] = 0.0
    for k in range(1, n + 1):
        for j in range(k * min_frames, T + 1):
            best, arg = INF, -1
            for i in range((k - 1) * min_frames, j - min_frames + 1):
                v = dp[k - 1][i]
                if v >= INF:
                    continue
                v += cost(i, j)
                if v < best:
                    best, arg = v, i
            dp[k][j] = best
            prev[k][j] = arg

    cuts = [T]
    j = T
    for k in range(n, 0, -1):
        j = int(prev[k][j])
        cuts.append(j)
    cuts.reverse()
    return cuts


def _trim_silence(x, sr, t0: float, t1: float, rel_db: float = -22.0):
    i0 = max(0, int(t0 * sr))
    i1 = min(len(x), int(t1 * sr))
    if i1 - i0 < sr // 25:
        return t0, t1
    db, hop_s = _db_curve(x[i0:i1], sr)
    if len(db) < 3:
        return t0, t1
    peak = float(np.max(db))
    if peak < -45.0:
        return t0, t1
    voiced = np.where(db > peak + rel_db)[0]
    if len(voiced) == 0:
        return t0, t1
    a = i0 / sr + voiced[0] * hop_s
    b = i0 / sr + (voiced[-1] + 1) * hop_s
    if b - a < 0.12:
        return t0, t1
    return max(t0, a), min(t1, b)


def _place_in_span(x, sr, t0: float, t1: float, n: int):
    if n <= 0:
        return []
    if n == 1:
        return [(round(t0, 3), round(t1, 3))]
    t0, t1 = _trim_silence(x, sr, t0, t1)
    i0, i1 = max(0, int(t0 * sr)), min(len(x), int(t1 * sr))
    bounds_t = None
    if i1 - i0 >= sr // 20 and (t1 - t0) / n >= 0.05:
        db, hop_s = _db_curve(x[i0:i1], sr)
        if len(db) >= n * 3:
            cuts = _dp_segment(db, n, max(2, int(0.035 / hop_s)))
            bounds_t = [t0 + c * hop_s for c in cuts]
    if bounds_t is None:
        bounds_t = list(np.linspace(t0, t1, n + 1))
    out = []
    for i in range(n):
        a, b = bounds_t[i], bounds_t[i + 1]
        if b - a < 0.02:
            b = a + 0.02
        out.append((round(a, 3), round(b, 3)))
    return out


def prune_outliers(spans, gap: float = 3.0):
    """Keep only the densest cluster of spans.

    Whisper sometimes emits one stray word far from the rest of a line (bleed
    from the previous phrase). Stretching the line across that hole would leave
    a mora lit for seconds, so the stray cluster is dropped.
    """
    if len(spans) <= 1:
        return spans
    spans = sorted(spans)
    clusters = [[spans[0]]]
    for a, b in spans[1:]:
        if a - clusters[-1][-1][1] > gap:
            clusters.append([(a, b)])
        else:
            clusters[-1].append((a, b))
    if len(clusters) == 1:
        return spans
    return max(clusters, key=lambda c: sum(b - a for a, b in c))


def place_morae_on_words(x, sr, word_spans, n_morae: int):
    """Distribute n_morae over whisper word spans, proportional to their length."""
    spans = [(float(a), float(b)) for a, b in word_spans if b - a > 0.02]
    spans = prune_outliers(spans)
    if not spans or n_morae <= 0:
        return []
    if len(spans) > n_morae:
        spans = sorted(spans, key=lambda p: p[1] - p[0], reverse=True)[:n_morae]
        spans.sort()

    durs = np.array([b - a for a, b in spans], dtype=float)
    total = durs.sum()
    if n_morae >= len(spans):
        counts = np.maximum(1, np.round(durs / total * n_morae).astype(int))
        while counts.sum() > n_morae:
            i = int(np.argmax(counts - durs / total * n_morae))
            if counts[i] <= 1:
                break
            counts[i] -= 1
        while counts.sum() < n_morae:
            counts[int(np.argmax(durs / total * n_morae - counts))] += 1
    else:
        counts = np.ones(len(spans), dtype=int)

    out = []
    for (a, b), c in zip(spans, counts):
        out.extend(_place_in_span(x, sr, a, b, int(c)))
    return out[:n_morae]


# --------------------------------------------------------------------------- #
# whisper
# --------------------------------------------------------------------------- #
def _enable_cuda_dlls() -> None:
    """ctranslate2 needs cuBLAS/cuDNN from torch's lib dir on Windows."""
    try:
        import torch
        lib = Path(torch.__file__).parent / "lib"
        if lib.is_dir():
            os.add_dll_directory(str(lib))
            os.environ["PATH"] = str(lib) + os.pathsep + os.environ.get("PATH", "")
    except Exception:  # noqa: BLE001
        pass


def _transcribe(x: np.ndarray, progress) -> list[dict]:
    """Transcribe a 16 kHz mono float32 array.

    Passing the array (rather than a path) keeps faster-whisper away from PyAV's
    ``av.open(..., metadata_errors=...)``, which older PyAV builds reject.
    """
    _enable_cuda_dlls()
    from faster_whisper import WhisperModel

    want = os.environ.get("UTALEARN_WHISPER", "large-v3")
    attempts = []
    try:
        import torch
        if torch.cuda.is_available():
            attempts.append((want, "cuda", "float16"))
    except Exception:  # noqa: BLE001
        pass
    attempts.append((want, "cpu", "int8"))
    attempts.append(("small", "cpu", "int8"))

    last = None
    for name, device, ctype in attempts:
        try:
            progress(0.10, f"载入 whisper {name}（{device}）…")
            model = WhisperModel(name, device=device, compute_type=ctype)
            progress(0.18, "识别歌声…")
            # VAD off: Silero rejects sung/spoken-over-music audio and returns
            # nothing, while raw decoding still finds the phrases.
            segs, _info = model.transcribe(
                x, language="ja", word_timestamps=True,
                vad_filter=False, beam_size=5,
                condition_on_previous_text=False,
                # No initial_prompt: on sung audio whisper tends to emit the
                # prompt itself as a lyric line, which then swallows the first
                # half-minute of real anchors.
            )
            out = []
            for s in segs:
                words = [{"w": w.word, "s": round(w.start, 3), "e": round(w.end, 3)}
                         for w in (s.words or []) if w.end > w.start]
                out.append({"start": round(s.start, 3), "end": round(s.end, 3),
                            "text": s.text.strip(), "words": words})
            return out
        except Exception as e:  # noqa: BLE001
            last = e
            continue
    raise RuntimeError(f"whisper 转写失败：{last}")


# --------------------------------------------------------------------------- #
# alignment
# --------------------------------------------------------------------------- #
def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = "".join(chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c for c in s)
    return PUNCT_RE.sub("", s)


def lcs_ratio(a: str, b: str) -> float:
    if not a or not b or len(a) > 240 or len(b) > 240:
        return 0.0
    lb = len(b)
    prev = [0] * (lb + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (lb + 1)
        ca = a[i - 1]
        for j in range(1, lb + 1):
            cur[j] = prev[j - 1] + 1 if ca == b[j - 1] else max(prev[j], cur[j - 1])
        prev = cur
    return prev[lb] / max(len(a), lb)


def align(lines: list[str], wsegs: list[dict]) -> list[dict | None]:
    """Global monotonic DP; returns one whisper segment (or None) per line."""
    n, m = len(lines), len(wsegs)
    lyr = [norm(x) for x in lines]
    seg = [norm(s["text"]) for s in wsegs]

    NEG = -1e9
    dp = [[NEG] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    for j in range(m + 1):
        dp[0][j] = 0.0
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0]
        back[i][0] = ("skip", 0)
        for j in range(1, m + 1):
            best, how = dp[i - 1][j], ("skip", 0)
            if dp[i][j - 1] > best:
                best, how = dp[i][j - 1], ("seg", 0)
            take = dp[i - 1][j - 1] + lcs_ratio(lyr[i - 1], seg[j - 1]) - MATCH_BONUS
            if take > best:
                best, how = take, ("take", 0)
            dp[i][j] = best
            back[i][j] = how

    out: list[dict | None] = [None] * n
    i, j = n, m
    while i > 0 and j >= 0:
        how = back[i][j]
        if how is None:
            break
        if how[0] == "take":
            out[i - 1] = wsegs[j - 1]
            i, j = i - 1, j - 1
        elif how[0] == "skip":
            i -= 1
        else:
            j -= 1
    return out


def _trim_uncovered_tail(lines: list[str], placed: list[dict | None]):
    """Drop lyric lines that the audio simply does not reach.

    A user's file is often only part of the song (a TV-size cut, one verse),
    while the lyric source describes the whole track. Those trailing lines have
    no anchor at all; spreading them over the leftover seconds would invent
    dozens of wrong lines. Keep them only while the tail is a plausible gap.
    """
    if not any(placed):
        return lines, placed
    last = max(i for i, p in enumerate(placed) if p is not None)
    matched = sum(1 for p in placed if p is not None)
    tail = len(lines) - last - 1
    if tail > max(2, matched):
        return lines[:last + 1], placed[:last + 1]
    return lines, placed


def _fill_gaps(placed: list[dict | None], lines: list[str], audio_end: float) -> None:
    n = len(placed)
    idx = 0
    while idx < n:
        if placed[idx] is not None:
            idx += 1
            continue
        run_start = idx
        while idx < n and placed[idx] is None:
            idx += 1
        run_end = idx

        prev_end = 0.0
        for k in range(run_start - 1, -1, -1):
            if placed[k] is not None:
                prev_end = placed[k]["end"]
                break
        next_start = audio_end
        for k in range(run_end, n):
            if placed[k] is not None:
                next_start = placed[k]["start"]
                break

        gap = max(0.4, next_start - prev_end)
        counts = [max(1, len(norm(lines[k]))) for k in range(run_start, run_end)]
        total = sum(counts) or 1
        t = prev_end
        for k, cnt in zip(range(run_start, run_end), counts):
            span = gap * cnt / total
            placed[k] = {"start": round(t, 3), "end": round(t + span, 3),
                         "text": "", "words": []}
            t += span


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
def _assign_times(text: str, tokens: list[dict], spans) -> list:
    """Map mora spans onto character indices of the line."""
    times: list[tuple[float, float] | None] = [None] * len(text)
    k = 0
    cursor = spans[0][0] if spans else 0.0
    for t in tokens:
        n = mora_count(t)
        if n <= 0:  # punctuation: a sliver of time at the cursor
            for i in range(t["start"], min(t["end"], len(text))):
                times[i] = (round(cursor, 3), round(cursor + 0.05, 3))
            continue
        take = spans[k:k + n]
        k += n
        if not take:
            continue
        a, b = take[0][0], take[-1][1]
        cursor = b
        m = max(1, t["end"] - t["start"])
        step = (b - a) / m
        for j in range(m):
            idx = t["start"] + j
            if idx < len(text):
                times[idx] = (round(a + j * step, 3), round(a + (j + 1) * step, 3))

    prev = spans[0][0] if spans else 0.0
    for i, tv in enumerate(times):
        if tv is None:
            times[i] = (round(prev, 3), round(prev, 3))
        else:
            prev = tv[1]
    return times


def build_from_audio(audio: str | Path, lines: list[str], meta: dict,
                     progress=None, wsegs: list[dict] | None = None) -> dict:
    """Estimate timing for `lines` from `audio`; returns a song_data dict.

    ``wsegs`` accepts an existing transcription. The retime path transcribes the
    audio first and falls back here when the fit is unreliable; passing that
    result in avoids paying for a second whisper pass over the whole song.
    """
    p = progress or (lambda frac, msg: None)
    lines = [ln.strip() for ln in lines if ln.strip()]
    if not lines:
        raise ValueError("歌词为空")

    p(0.04, "解码音频…")
    wav = to_wav(audio)
    try:
        x, sr = load_wav(wav)
        p(0.08, f"音频 {len(x) / sr:.1f}s")
        if wsegs is None:
            wsegs = _transcribe(x, p)
        if not wsegs:
            raise RuntimeError("没有识别到任何歌声，请检查音频或歌词")

        p(0.58, f"对齐 {len(lines)} 行歌词…")
        # Two passes: the first locates how far the audio actually reaches, so a
        # lyric source describing the full track cannot drag the DP alignment
        # of the lines that *are* covered.
        placed = align(lines, wsegs)
        kept_lines, _ = _trim_uncovered_tail(lines, placed)
        if len(kept_lines) < len(lines):
            p(0.60, f"音频只覆盖前 {len(kept_lines)} 行，重新对齐…")
            lines = kept_lines
            placed = align(lines, wsegs)

        # Use the real audio length, not the last whisper segment: when whisper
        # gives up on the outro, the remaining lines still need somewhere to go
        # instead of being crammed at the last anchor.
        audio_end = len(x) / sr
        _fill_gaps(placed, lines, audio_end)

        p(0.68, "按人声能量定位每个音…")
        segments = []
        for li, seg in enumerate(placed):
            text = lines[li]
            tokens = analyze(text)
            if not tokens:
                continue
            _prefer_kana_lemma(tokens)
            total = sum(mora_count(t) for t in tokens)
            anchors = [(w["s"], w["e"]) for w in seg.get("words", [])
                       if w["e"] - w["s"] > 0.02]
            spans = place_morae_on_words(x, sr, anchors, total) if total else []
            if not spans:
                spans = _even(seg["start"], seg["end"], max(1, total))
            times = _assign_times(text, tokens, spans)
            enrich(tokens)
            # Grammar first: a word that sits inside a detected pattern is
            # grammar material, not vocabulary. わけ in わけにはいかない must not
            # surface as "原因；理由". This has to happen here because only the
            # tokens still know their character offsets -- the stored word
            # start/end are seconds, so the UI cannot work this out.
            grammar = find_grammar(text, tokens)
            gspans = [(g["at"], g["at"] + len(g["matched"])) for g in grammar]

            def _in_grammar(tok: dict) -> bool:
                return any(tok["start"] < b and a < tok["end"] for a, b in gspans)

            words = []
            for t in tokens:
                rng = range(t["start"], min(t["end"], len(text)))
                seg_chars = [{"ch": text[i], "start": times[i][0], "end": times[i][1]}
                             for i in rng if times[i]]
                if not seg_chars:
                    continue
                w = {
                    "text": t["surface"], "lemma": t["lemma"],
                    "pos": t["pos"], "pos1": t["pos1"],
                    "start": seg_chars[0]["start"], "end": seg_chars[-1]["end"],
                    "score": round(0.55 + 0.35 * lcs_ratio(norm(text), norm(seg.get("text", ""))), 3),
                    "chars": seg_chars,
                    "content": is_content(t) and not _in_grammar(t),
                }
                if t.get("kana"):
                    w["kana"] = t["kana"]
                w["romaji"] = "" if all(c in " \u3000、。,.!?！？…「」『』()（）・~〜-—" for c in t["surface"]) else t["romaji"]
                if t.get("zh"):
                    w["zh"] = t["zh"]
                if t.get("jlpt"):
                    w["jlpt"] = t["jlpt"]
                if t.get("lemma_kana"):
                    w["lemma_kana"] = t["lemma_kana"]
                words.append(w)
            if not words:
                continue

            entry = {
                "id": len(segments),
                "start": round(words[0]["start"], 3),
                "end": round(words[-1]["end"], 3),
                "text": text,
                "romaji": " ".join(w["romaji"] for w in words if w["romaji"]),
                "words": words,
            }
            if grammar:
                entry["grammar"] = grammar
            segments.append(entry)

        if not segments:
            raise RuntimeError("歌词与音频没有对齐出任何一行")

        duration = probe_duration(audio) or round(segments[-1]["end"], 2)
        p(0.96, f"完成 {len(segments)} 行")
        return {
            "meta": {
                "language": "ja",
                "duration_seconds": round(duration, 2),
                "generated_at": meta.pop("generated_at", None) or _now(),
                **meta,
            },
            "segments": segments,
        }
    finally:
        try:
            wav.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
