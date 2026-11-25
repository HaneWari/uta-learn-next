"""Re-align one already-built line against its own audio window (5.3.3).

Whole-song alignment is right on average but a single line can land late — a
held note, a whispered phrase, a line that starts in the previous breath. The
fix used to be "regenerate the whole song", which costs a full whisper pass for
one wrong line.

This module takes only ±5 s around the line, transcribes that window, runs the
same kana Needleman–Wunsch the full build uses, and returns fresh per-character
times. The rest of the dataset is untouched.

Requires the custom-lyrics extension pack (whisper); without it the caller gets
an actionable Chinese error and the UI keeps the button disabled.
"""
from __future__ import annotations

from pathlib import Path

from app import fallback

WINDOW = 5.0
MIN_WINDOW = 1.0


def realign_line(audio: str | Path, text: str, start: float, end: float,
                 progress=None) -> dict:
    """Return `{"start", "end", "chars": [...]}` for one line.

    `chars` is the per-glyph timing shape `song_data.json` already stores, so
    the caller can drop it straight into `segment.words[i].chars`.
    """
    p = progress or (lambda frac, msg: None)
    text = (text or "").strip()
    if not text:
        raise ValueError("这一行没有文字,无法重新对齐")
    if end <= start:
        raise ValueError("这一行的时间轴无效")

    lo = max(0.0, start - WINDOW)
    hi = end + WINDOW
    if hi - lo < MIN_WINDOW:
        raise ValueError("音频窗口太短")

    p(0.05, "裁出这一行的音频…")
    clip = fallback.to_wav_window(audio, lo, hi)
    try:
        p(0.15, "识别这一句…")
        x, sr = fallback.load_wav(clip)
        if not len(x):
            raise RuntimeError("这一段没有声音")
        words, _label = fallback._transcribe_chunked(x, sr, p)
        if not words:
            raise RuntimeError("这一句没有识别到歌声,可能只有伴奏")

        # whisper gives times relative to the clip; shift them back onto the song
        shifted = [{"w": w["w"], "s": w["s"] + lo, "e": w["e"] + lo}
                   for w in words]
        p(0.65, "重新按假名对齐…")
        prepared = [item for item in (fallback._prepare(text),) if item]
        if not prepared:
            raise ValueError("这一行的歌词无法分词")
        kana, rows = fallback._locate(prepared, shifted)
        if not any(rows):
            raise RuntimeError(
                "这一句在前后 5 秒里找不到对应的歌声,请先确认歌词文本是否正确")
        timed = fallback._line_times(kana, rows, hi, clip_tail=False)
        (prep, (t0, _a, t1, _cov)) = prepared[0], timed[0]
        line_text, tokens, kls = prep
        times = fallback._assign_times(line_text, tokens, kls, t0, t1)
        chars = [
            {"ch": line_text[i], "start": round(times[i][0], 3),
             "end": round(times[i][1], 3)}
            for i in range(len(line_text)) if times[i]
        ]
        p(0.98, "完成")
        return {"start": round(t0, 3), "end": round(t1, 3), "chars": chars}
    finally:
        try:
            clip.unlink(missing_ok=True)
        except OSError:
            pass
