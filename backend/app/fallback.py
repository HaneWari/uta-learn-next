"""Fallback timing: chunked whisper transcription + global kana alignment.

Used when no lyric source has the song, or the user prefers to build from their
own audio. The lyrics are the user's (or the source's) text; only the *timing*
is estimated here.

Pipeline
--------
1. Decode the upload to 16 kHz mono PCM with ffmpeg.
2. Transcribe in overlapping 30 s windows and keep only each window's trusted
   middle. Whisper's word timestamps drift badly over a whole song (it was
   trained on 30 s clips), while inside one short window they stay tight; the
   discarded window edges are where it guesses words cut in half.
3. Align *all* lyric kana against *all* transcript kana in one global
   Needleman–Wunsch pass. Comparing readings rather than text survives whisper
   writing 時 where the lyric has とき, and one global pass means a line whisper
   missed can never drag the rest of the timeline out of order.
4. Every matched kana takes its time from the transcript word it matched;
   unmatched kana inside a line are interpolated, the ends extrapolated at the
   line's own singing rate, and lines with no anchors are spread over the gap
   between their neighbours.

On a benchmark of three songs with source per-character timestamps this lands
the mean character error around 0.3 s (the previous whole-track + vocal energy
pipeline: ~1.6 s).
"""
from __future__ import annotations

from . import binaries

import os
import re
import subprocess
import tempfile
import unicodedata
import wave
from pathlib import Path

import numpy as np

from .builder import _prefer_kana_lemma
from .dicts import (analyze, apply_reading_marks, enrich, find_grammar,
                    is_content, parse_reading_marks)

PUNCT_RE = re.compile(r"[\s、。,.!?！？…「」『』()（）・~〜\-—:;\"'’“”]")
JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
MATCH_BONUS = 0.55

CHUNK_WIN = 30.0
CHUNK_EDGE = 6.0

KANA_MATCH = 1.0
KANA_MISMATCH = -0.6
KANA_GAP = -0.4

MIN_COVERAGE = 0.3
DEFAULT_RATE = 0.3
MIN_RATE, MAX_RATE = 0.15, 0.6
FIRST_WORD_CAP = 0.5
ANCHOR_GAP = 4.0


# --------------------------------------------------------------------------- #
# audio
# --------------------------------------------------------------------------- #
def to_wav(src: str | Path, dst: str | Path | None = None) -> Path:
    """Decode anything ffmpeg reads into 16 kHz mono 16-bit PCM."""
    dst = Path(dst) if dst else Path(tempfile.gettempdir()) / f"utalearn_{os.getpid()}.wav"
    cmd = [binaries.ffmpeg(), "-y", "-v", "error", "-i", str(src),
           "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", str(dst)]
    subprocess.run(cmd, check=True, capture_output=True)
    return dst


def probe_duration(src: str | Path) -> float:
    cmd = [binaries.ffprobe(), "-v", "error", "-show_entries", "format=duration",
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


def _run_whisper(progress, fn):
    """Load the bundled model and run ``fn(model)``; returns (result, label).

    Each (model, device) attempt runs the whole job, so a CUDA build that loads
    but fails on the first decode (missing cuDNN) still falls back to the CPU.
    """
    _enable_cuda_dlls()
    from faster_whisper import WhisperModel

    attempts = _model_attempts()
    if not attempts:
        raise RuntimeError(_model_missing_msg())

    last = None
    for name, device, ctype in attempts:
        try:
            progress(0.10, f"载入 whisper {_label(name)}（{device}）…")
            model = WhisperModel(str(name), device=device, compute_type=ctype)
            return fn(model), _label(name)
        except Exception as e:  # noqa: BLE001
            last = e
            continue
    # a bundled model was found but failed to load — that is a broken pack or a
    # real decode fault, not a missing model
    raise RuntimeError(f"whisper 转写失败：{last}")


def _decode(model, x: np.ndarray):
    # VAD off: Silero rejects sung/spoken-over-music audio and returns nothing,
    # while raw decoding still finds the phrases. No initial_prompt: on sung
    # audio whisper tends to emit the prompt itself as a lyric line.
    segs, _info = model.transcribe(
        x, language="ja", word_timestamps=True, vad_filter=False, beam_size=5,
        condition_on_previous_text=False)
    return segs


def _transcribe(x: np.ndarray, progress) -> list[dict]:
    """Whole-track transcription as whisper segments (used by the retime fit).

    Passing the array (rather than a path) keeps faster-whisper away from PyAV's
    ``av.open(..., metadata_errors=...)``, which older PyAV builds reject.
    """
    def work(model):
        progress(0.18, "识别歌声…")
        out = []
        for s in _decode(model, x):
            words = [{"w": w.word, "s": round(w.start, 3), "e": round(w.end, 3)}
                     for w in (s.words or []) if w.end > w.start]
            out.append({"start": round(s.start, 3), "end": round(s.end, 3),
                        "text": s.text.strip(), "words": words})
        return out

    return _run_whisper(progress, work)[0]


def _chunk_starts(duration: float) -> list[float]:
    """Window starts whose trusted middles tile the track exactly.

    Stops at the first window that reaches the end, otherwise the last trusted
    zones would overlap and the same words be counted twice.
    """
    hop = CHUNK_WIN - 2 * CHUNK_EDGE
    starts, t = [0.0], 0.0
    while t + CHUNK_WIN < duration:
        t += hop
        starts.append(t)
    return starts


def _transcribe_chunked(x: np.ndarray, sr: int, progress) -> tuple[list[dict], str]:
    """Word list ``[{w, s, e}]`` from short overlapping windows."""
    dur = len(x) / sr
    starts = _chunk_starts(dur)

    def work(model):
        out = []
        for k, a in enumerate(starts):
            progress(0.18 + 0.38 * k / len(starts), f"识别歌声（{k + 1}/{len(starts)} 段）…")
            b = min(dur, a + CHUNK_WIN)
            lo = a + (CHUNK_EDGE if a > 0 else 0.0)
            hi = b - (CHUNK_EDGE if b < dur else 0.0)
            for s in _decode(model, x[int(a * sr):int(b * sr)]):
                for w in (s.words or []):
                    gs, ge = a + w.start, a + w.end
                    if ge > gs and lo <= (gs + ge) / 2 < hi:
                        out.append({"w": w.word, "s": round(gs, 3), "e": round(ge, 3)})
        return out

    words, label = _run_whisper(progress, work)
    words.sort(key=lambda d: d["s"])
    dedup: list[dict] = []
    for w in words:
        if dedup and w["w"] == dedup[-1]["w"] and w["s"] - dedup[-1]["s"] < 0.35:
            continue
        dedup.append(w)
    return dedup, label


# --------------------------------------------------------------------------- #
# bundled whisper model: models/<name>/ next to the app
# --------------------------------------------------------------------------- #
# The model is *never* downloaded: the portable build ships `small` as an
# optional extension pack (`models/whisper-small/`, a plain ctranslate2 folder
# the loader reads straight off disk), and the config page offers a one-click
# fetch of that same zip from the release page. No HF cache, no network — a
# missing pack is a hard, actionable error rather than a surprise 500MB pull.

def _model_root() -> Path:
    """Folder that holds bundled models: <app>/models (writable or not)."""
    return Path(__file__).resolve().parents[2] / "models"


def _model_missing_msg() -> str:
    return (
        "未找到语音识别模型。这个功能需要「自定义歌词模型扩展包」：在配置页点"
        "「下载并安装扩展」一键装好，或到发行版页面下载 "
        "UtaLearnNext-custom-lyrics.zip，解压到应用目录的 models/ 下"
        "（得到 models/whisper-small/）后重启。"
    )


def _local_model_dirs() -> list[Path]:
    root = _model_root()
    if not root.is_dir():
        return []
    return [p for p in sorted(root.iterdir()) if p.is_dir()]


def _label(name) -> str:
    return Path(str(name)).name if os.sep in str(name) else str(name)


def _model_attempts() -> list[tuple[str | Path, str, str]]:
    """Ordered (model, device, compute_type) tries.

    Only bundled `models/<name>/` dirs are tried — the model is local by
    contract, never pulled over the network. CUDA goes first when torch sees a
    GPU, with the CPU kept as a fallback for a broken CUDA runtime.
    """
    local = _local_model_dirs()
    if not local:
        return []
    cuda_ok = False
    try:
        import torch
        if torch.cuda.is_available():
            cuda_ok = True
    except Exception:  # noqa: BLE001
        pass
    cpu = [(n, "cpu", "int8") for n in local]
    return [(n, "cuda", "float16") for n in local] + cpu if cuda_ok else cpu


# --------------------------------------------------------------------------- #
# text helpers (also used by the retime fit)
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


# --------------------------------------------------------------------------- #
# kana alignment
# --------------------------------------------------------------------------- #
def _tok_kana(tok: dict) -> str:
    return norm(tok.get("kana") or tok["surface"]).lower()


_KANA_CACHE: dict[str, str] = {}


def _text_kana(text: str) -> str:
    """Reading of a transcript word: whisper writes kanji, the lyric may not."""
    hit = _KANA_CACHE.get(text)
    if hit is None:
        toks = analyze(text) or []
        hit = "".join(_tok_kana(t) for t in toks) if toks else norm(text).lower()
        if len(_KANA_CACHE) > 20000:
            _KANA_CACHE.clear()
        _KANA_CACHE[text] = hit
    return hit


def _kana_match(line_kana: list[str], words: list[dict]) -> list[list[tuple | None]]:
    """Needleman–Wunsch of every lyric kana against every transcript kana.

    Returns, per line, one entry per kana: ``(word_index, offset, word_len)``
    when it matched a transcript kana, else None. Transcript kana before the
    first and after the last lyric kana are free (intro chatter, outro ad-libs).
    So are lyric kana before the first and after the last transcript kana: a
    clip of the song leaves whole lines unsung, and with a costed tail a
    repeated chorus would tie and could pull the clip's last words onto the
    song's final repeat instead of the lines it actually reaches.
    """
    L, lid, lpos = [], [], []
    for i, k in enumerate(line_kana):
        for p, c in enumerate(k):
            L.append(c)
            lid.append(i)
            lpos.append(p)
    T, wid, woff = [], [], []
    wkana = [_text_kana(w["w"]) for w in words]
    for k, wk in enumerate(wkana):
        for o, c in enumerate(wk):
            T.append(c)
            wid.append(k)
            woff.append(o)
    res: list[list[tuple | None]] = [[None] * len(k) for k in line_kana]
    n, m = len(L), len(T)
    if not n or not m:
        return res

    width = m + 1
    prev = [0.0] * width
    back = bytearray((n + 1) * width)
    for i in range(1, n + 1):
        cur = [0.0] * width
        back[i * width] = 1
        li = L[i - 1]
        row = i * width
        tail_gap = KANA_GAP if i < n else 0.0
        for j in range(1, width):
            d = prev[j - 1] + (KANA_MATCH if li == T[j - 1] else KANA_MISMATCH)
            u = prev[j] + (KANA_GAP if j < m else 0.0)
            lft = cur[j - 1] + tail_gap
            if d >= u and d >= lft:
                cur[j] = d
            elif u >= lft:
                cur[j] = u
                back[row + j] = 1
            else:
                cur[j] = lft
                back[row + j] = 2
        prev = cur

    i, j = n, m
    while i > 0 and j > 0:
        b = back[i * width + j]
        if b == 0:
            if L[i - 1] == T[j - 1]:
                k = wid[j - 1]
                res[lid[i - 1]][lpos[i - 1]] = (k, woff[j - 1], len(wkana[k]))
            i, j = i - 1, j - 1
        elif b == 1:
            i -= 1
        else:
            j -= 1
    return res


def _anchor_rows(res: list[list[tuple | None]], words: list[dict]):
    """Per line: (kana times with None gaps, matched indices, coverage) or None.

    A line needs a fair share of its kana matched to count as found; a couple
    of stray hits are as likely to be a neighbouring line's words.
    """
    rows = []
    for mt in res:
        n = len(mt)
        hits = [p for p in range(n) if mt[p]]
        if len(hits) < max(2, MIN_COVERAGE * n):
            rows.append(None)
            continue
        first_word = mt[hits[0]][0]
        t: list[float | None] = [None] * n
        last = -1.0
        for p in hits:
            k, off, wl = mt[p]
            s, e = words[k]["s"], words[k]["e"]
            # whisper stretches a line's first word back over the breath or the
            # instrumental before it; a sung kana rarely lasts longer than this
            if k == first_word and (e - s) / wl > FIRST_WORD_CAP:
                s = e - FIRST_WORD_CAP * wl
            v = s + (e - s) * off / wl
            if v > last:
                t[p] = v
                last = v
        hits = [p for p in range(n) if t[p] is not None]
        # A few kana of a line can meet the same kana many seconds away (a
        # chorus repeat, an ad-lib) and would stretch the line across that
        # hole; keep only the densest run of anchors.
        runs = [[hits[0]]]
        for q in hits[1:]:
            if t[q] - t[runs[-1][-1]] > ANCHOR_GAP:
                runs.append([q])
            else:
                runs[-1].append(q)
        if len(runs) > 1:
            keep = max(runs, key=len)
            for q in hits:
                if q not in keep:
                    t[q] = None
            hits = keep
            if len(hits) < max(2, MIN_COVERAGE * n):
                rows.append(None)
                continue
        rows.append((t, hits, len(hits) / max(1, n)))
    return rows


def _line_times(line_kana: list[str], rows, audio_end: float,
                clip_tail: bool = False):
    """Fill every line's kana times; returns [(times, start, end, coverage)]."""
    count = len(line_kana)
    out: list[tuple | None] = [None] * count
    for li in range(count):
        row = rows[li]
        if row is None:
            continue
        t, hits, cov = row
        n = len(t)
        prev_end = next((rows[k][0][rows[k][1][-1]] for k in range(li - 1, -1, -1)
                         if rows[k]), 0.0)
        next_start = next((rows[k][0][rows[k][1][0]] for k in range(li + 1, count)
                           if rows[k]), audio_end)
        a, b = hits[0], hits[-1]
        r = (t[b] - t[a]) / (b - a) if b > a else DEFAULT_RATE
        r = min(MAX_RATE, max(MIN_RATE, r))
        for p in range(a):
            t[p] = max(prev_end + 0.05 * (p + 1), t[a] - (a - p) * r)
        for x, y in zip(hits, hits[1:]):
            for p in range(x + 1, y):
                t[p] = t[x] + (t[y] - t[x]) * (p - x) / (y - x)
        for p in range(b + 1, n):
            t[p] = min(next_start - 0.05 * (n - p), t[b] + (p - b) * r)
        for p in range(1, n):
            t[p] = max(t[p], t[p - 1])
        end = max(t[-1], min(next_start, t[-1] + r))
        out[li] = (t, t[0], end, cov)

    li = 0
    while li < count:
        if out[li] is not None:
            li += 1
            continue
        j = li
        while j < count and out[j] is None:
            j += 1
        sizes = [len(line_kana[k]) or 1 for k in range(li, j)]
        tot = sum(sizes)
        t0 = out[li - 1][2] if li > 0 else None
        t1 = out[j][1] if j < count else None
        # an unmatched head or tail run has only one neighbour: sing it at a
        # plausible pace next to that neighbour instead of smearing it across
        # the whole intro / outro
        if t0 is None:
            t1 = t1 if t1 is not None else audio_end
            t0 = max(0.0, t1 - FIRST_WORD_CAP * tot)
        elif t1 is None:
            # A clip that started mid-song is almost certainly cut off at the
            # end too; run the unmatched tail past the file at a natural pace
            # rather than crushing it into the last seconds.
            t1 = t0 + FIRST_WORD_CAP * tot if clip_tail else min(
                max(audio_end, t0), t0 + FIRST_WORD_CAP * tot)
        cur = t0
        for k, nk in zip(range(li, j), sizes):
            span = max(0.0, t1 - t0) * nk / tot
            out[k] = ([cur + span * q / nk for q in range(nk)], cur, cur + span, 0.0)
            cur += span
        li = j
    return out


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
def _assign_times(text: str, tokens: list[dict], kls: list[int],
                  t: list[float], end: float) -> list:
    """Map the line's kana times onto character indices of `text`.

    A token owns the time from its first kana to the next token's first kana,
    shared evenly over its characters (kanji carry several kana each).
    """
    times: list[tuple[float, float] | None] = [None] * len(text)
    n = len(t)
    p = 0
    for tok, kl in zip(tokens, kls):
        a = t[p] if p < n else end
        if kl == 0:
            b = min(a + 0.05, max(a, end))
        else:
            b = t[p + kl] if p + kl < n else end
        b = max(a, b)
        rng = range(tok["start"], min(tok["end"], len(text)))
        step = (b - a) / max(1, len(rng))
        for q, i in enumerate(rng):
            times[i] = (round(a + q * step, 3), round(a + (q + 1) * step, 3))
        p += kl

    prev = t[0] if t else 0.0
    for i, tv in enumerate(times):
        if tv is None:
            times[i] = (round(prev, 3), round(prev, 3))
        else:
            prev = tv[1]
    return times


def _prepare(raw: str):
    """Tokenise one lyric line; returns (text, tokens, kana lengths) or None.

    `[汉字](よみ)` marks are markup, never sung: they are stripped before the
    tagger, and the marked reading replaces the token's kana *before* the
    alignment, so a custom reading also steers which transcript kana it meets.
    """
    text, marks = parse_reading_marks(raw)
    tokens = analyze(text)
    if not tokens:
        return None
    apply_reading_marks(text, tokens, marks)
    _prefer_kana_lemma(tokens)
    return text, tokens, [len(_tok_kana(t)) for t in tokens]


def _locate(prepared: list, words: list[dict]):
    kana = ["".join(_tok_kana(t) for t in tokens) for _, tokens, _ in prepared]
    return kana, _anchor_rows(_kana_match(kana, words), words)


def build_from_audio(audio: str | Path, lines: list[str], meta: dict,
                     progress=None, words: list[dict] | None = None) -> dict:
    """Estimate timing for `lines` from `audio`; returns a song_data dict.

    ``words`` accepts an existing chunked transcription (``[{w, s, e}]``),
    skipping the whisper pass.
    """
    p = progress or (lambda frac, msg: None)
    lines = [ln.strip() for ln in lines if ln.strip()]
    prepared = [x for x in (_prepare(ln) for ln in lines) if x]
    if not prepared:
        raise ValueError("歌词为空")

    p(0.04, "解码音频…")
    wav = to_wav(audio)
    try:
        x, sr = load_wav(wav)
        audio_end = len(x) / sr
        p(0.08, f"音频 {audio_end:.1f}s")
        if words is None:
            words, label = _transcribe_chunked(x, sr, p)
            meta["whisperx_model"] = label
    finally:
        try:
            wav.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
    if not words:
        raise RuntimeError("没有识别到任何歌声，请检查音频或歌词")

    p(0.58, f"按假名对齐 {len(prepared)} 行歌词…")
    kana, rows = _locate(prepared, words)
    found = [i for i, r in enumerate(rows) if r]
    if not found:
        raise RuntimeError("歌词与音频对不上：没有一行能在歌声里找到，请确认歌词和音频是同一首歌")
    # A user's file is often only part of the song (a TV-size cut, one verse)
    # while the pasted lyrics describe the whole track. Leading / trailing
    # lines with no anchor at all would otherwise be invented across the
    # leftover seconds; a short unmatched run is kept as an ordinary miss.
    lo, hi = 0, len(prepared)
    # More than a couple of leading lines unmatched means the clip starts
    # mid-song; a stray missed line or two is kept as an ordinary miss.
    if found[0] > 2:
        lo = found[0]
    if len(prepared) - found[-1] - 1 > max(2, len(found)):
        hi = found[-1] + 1
    if (lo, hi) != (0, len(prepared)):
        p(0.60, f"音频只覆盖第 {lo + 1}–{hi} 行，重新对齐…")
        prepared = prepared[lo:hi]
        kana, rows = _locate(prepared, words)

    p(0.68, "逐字定位…")
    # The effective end of sung content is the last transcript word, not the
    # file's total duration: an instrumental tail would otherwise pull the
    # unmatched lines into silence that still counts as "before the end".
    song_end = words[-1]["e"] if words else audio_end
    timed = _line_times(kana, rows, song_end, clip_tail=lo > 0)

    segments = []
    for (text, tokens, kls), (t, _start, end, cov) in zip(prepared, timed):
        times = _assign_times(text, tokens, kls, t, end)
        enrich(tokens)
        # Grammar first: a word that sits inside a detected pattern is grammar
        # material, not vocabulary. わけ in わけにはいかない must not surface as
        # "原因；理由". This has to happen here because only the tokens still
        # know their character offsets -- the stored word start/end are
        # seconds, so the UI cannot work this out.
        grammar = find_grammar(text, tokens)
        gspans = [(g["at"], g["at"] + len(g["matched"])) for g in grammar]

        def _in_grammar(tok: dict) -> bool:
            return any(tok["start"] < b and a < tok["end"] for a, b in gspans)

        out_words = []
        for tk in tokens:
            rng = range(tk["start"], min(tk["end"], len(text)))
            seg_chars = [{"ch": text[i], "start": times[i][0], "end": times[i][1]}
                         for i in rng if times[i]]
            if not seg_chars:
                continue
            w = {
                "text": tk["surface"], "lemma": tk["lemma"],
                "pos": tk["pos"], "pos1": tk["pos1"],
                "start": seg_chars[0]["start"], "end": seg_chars[-1]["end"],
                "score": round(0.55 + 0.35 * cov, 3),
                "chars": seg_chars,
                "content": is_content(tk) and not _in_grammar(tk),
            }
            if tk.get("kana"):
                w["kana"] = tk["kana"]
            w["romaji"] = "" if all(c in " \u3000、。,.!?！？…「」『』()（）・~〜-—" for c in tk["surface"]) else tk["romaji"]
            if tk.get("zh"):
                w["zh"] = tk["zh"]
            if tk.get("jlpt"):
                w["jlpt"] = tk["jlpt"]
            if tk.get("lemma_kana"):
                w["lemma_kana"] = tk["lemma_kana"]
            out_words.append(w)
        if not out_words:
            continue

        entry = {
            "id": len(segments),
            "start": round(out_words[0]["start"], 3),
            "end": round(max(out_words[-1]["end"], end), 3),
            "text": text,
            "romaji": " ".join(w["romaji"] for w in out_words if w["romaji"]),
            "words": out_words,
        }
        if grammar:
            entry["grammar"] = grammar
        segments.append(entry)

    if not segments:
        raise RuntimeError("歌词与音频没有对齐出任何一行")

    # A line's extrapolated head may reach back past where the previous line's
    # tail was extrapolated to; end the earlier line there so two lines never
    # claim the same instant.
    for cur, nxt in zip(segments, segments[1:]):
        cut = nxt["start"]
        if cur["end"] <= cut:
            continue
        cur["end"] = max(cur["start"], cut)
        for w in cur["words"]:
            for c in w["chars"]:
                c["start"] = min(c["start"], cur["end"])
                c["end"] = min(c["end"], cur["end"])
            w["start"] = w["chars"][0]["start"]
            w["end"] = w["chars"][-1]["end"]

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


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
