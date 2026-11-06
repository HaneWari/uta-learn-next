"""Turn parsed lyrics into the app's `song_data.json` schema.

Two timing shapes arrive from the sources:

* ``kind="char"`` — QQ Music / Kugou give a start+duration per character, so the
  highlight can advance glyph by glyph.
* ``kind="line"`` — Lrclib only knows where each line starts. Those lines are
  spread over the line span weighted by each word's mora count, which tracks
  sung length far better than an even split.

In both cases the *word* units come from fugashi (UniDic): real morphemes with
lemma, part of speech and reading — not the hand-split phrases the old build
used. Every word is then enriched with a Chinese gloss / JLPT level, and each
line is annotated with the grammar patterns it contains.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .dicts import analyze, enrich, find_grammar, is_content, is_punct, mora_count
from .sources import ParsedLyrics

PUNCT = set(" \u3000\t、。,.!?！？…「」『』()（）・~〜-—–:;\"'’“”　")

# QRC/KRC carry the credit block (title / lyricist / composer) as timed lines.
# They are not sung, so they must never become a lyric segment.
CREDIT_RE = re.compile(
    r"^\s*(作[詞词]|作曲|編曲|编曲|曲|詞|词|歌|演唱|混音|録音|录音|制作|監修|监修|訳|译"
    r"|Lyrics?|Music|Composer|Arranger)"
    r"\s*[:：]", re.IGNORECASE)


def _squeeze(text: str) -> str:
    return re.sub(r"[\s\u3000]+", "", str(text or "")).lower()


def _is_credit(text: str, meta: dict, head: bool = False) -> bool:
    """Is this a credit/header line rather than a sung line?

    ``head`` marks the first few lines, where sources put the title block; only
    there do we treat a line containing the title or artist as a credit, so a
    chorus that repeats the title is never dropped.
    """
    t = text.strip()
    if CREDIT_RE.match(t):
        return True
    if not head:
        return False
    key = _squeeze(t)
    if not key:
        return True
    for field in ("title", "artist"):
        raw = str(meta.get(field) or "")
        for part in (raw, re.split(r"[(\（\[【]", raw)[0]):
            other = _squeeze(part)
            if len(other) >= 2 and other in key:
                return True
    return False


def _split_units(units: list[tuple[str, float, float]]) -> list[dict]:
    """Expand ``(text, start, end)`` units into one entry per character.

    QRC sometimes carries a whole English word as one unit; splitting it evenly
    keeps ``chars`` index-aligned with the line's text.
    """
    out: list[dict] = []
    for text, start, end in units:
        n = len(text)
        if n == 0:
            continue
        if n == 1:
            out.append({"ch": text, "start": round(start, 3), "end": round(end, 3)})
            continue
        step = (end - start) / n
        for k, ch in enumerate(text):
            out.append({
                "ch": ch,
                "start": round(start + k * step, 3),
                "end": round(start + (k + 1) * step, 3),
            })
    return out


def _prefer_kana_lemma(tokens: list[dict]) -> None:
    """Drop a rare kanji lemma when the dictionary knows the word as kana.

    UniDic returns 急度 for きっと; the bundled dictionary lists that word under
    its reading, which means it is normally written in kana. Showing 急度 would
    teach a spelling nobody uses.
    """
    from .dicts import _dict  # local import: keeps module import cheap

    d = _dict()
    for t in tokens:
        reading = t.get("kana") or ""
        entry = d.get(reading) if reading else None
        # a dictionary key that equals its own reading means the word is
        # normally written in kana, so the kanji lemma is a rare spelling
        if entry and entry.get("k") == reading:
            t["lemma"] = t["surface"]


def _times_by_mora(text: str, start: float, end: float,
                   tokens: list[dict]) -> list[dict]:
    """Spread ``[start, end]`` over ``text`` weighted by each word's morae.

    Line-level sources give no intra-line timing, so the relative length of each
    word's reading is the best available signal.
    """
    weights = []
    for t in tokens:
        n = mora_count(t)
        weights.append(n if n else 0.5)
    total = sum(weights) or 1.0
    span_all = max(0.05, end - start)

    times: list[tuple[float, float] | None] = [None] * len(text)
    cursor = start
    for tok, w in zip(tokens, weights):
        span = span_all * w / total
        a = cursor
        cursor += span
        n = max(1, tok["end"] - tok["start"])
        step = span / n
        for k in range(tok["start"], min(tok["end"], len(text))):
            times[k] = (round(a + (k - tok["start"]) * step, 3),
                        round(a + (k - tok["start"] + 1) * step, 3))

    # tokens never cover whitespace, so interpolate across the holes
    last = start
    for i, tv in enumerate(times):
        if tv is None:
            times[i] = (round(last, 3), round(last, 3))
        else:
            last = tv[1]

    return [{"ch": text[i], "start": tv[0], "end": tv[1]}
            for i, tv in enumerate(times) if tv is not None]


def _match_translation(trans: list[tuple[float, str]], start: float,
                       tol: float = 0.7) -> str | None:
    if not trans:
        return None
    best_t, best_s = min(trans, key=lambda p: abs(p[0] - start))
    if abs(best_t - start) <= tol:
        return best_s
    return None


def build(parsed: ParsedLyrics, meta: dict, offset: float = 0.0,
          credit_names: dict | None = None,
          time_scale: float = 1.0,
          time_shift: float | None = None,
          max_time: float | None = None) -> dict:
    """ParsedLyrics -> song_data dict.

    Timestamps are remapped by ``t' = time_scale * t + time_shift``. That covers
    the two ways a user's file can differ from the recording the lyrics were
    timed against: a different start point (``time_shift``) and a different
    playback speed (``time_scale``). ``offset`` is the historical shorthand for
    ``time_shift = -offset`` and still works.

    ``max_time`` clips the result to an audio length, so a lyric source that
    describes the whole track cannot place lines past the end of a shorter file.

    ``credit_names`` overrides the title/artist used to recognise the header
    block. A source payload repeats the *release* title, which is usually not
    the label the user typed, so passing the source's own names is what actually
    catches the credit line.
    """
    credit_meta = credit_names or meta
    if time_shift is None:
        time_shift = -offset

    def remap(t: float) -> float:
        # never emit a negative timestamp: after a shift the first line can
        # otherwise start before zero, which the player cannot show
        return round(max(0.0, time_scale * t + time_shift), 3)

    trans = [(remap(t), s) for t, s in (parsed.translation or [])
             if max_time is None or remap(t) <= max_time]
    segments: list[dict] = []

    for raw_index, line in enumerate(parsed.lines):
        units = line.get("units") or []
        if not units:
            continue
        chars = _split_units(units)
        text = "".join(c["ch"] for c in chars)
        if not text.strip() or _is_credit(text, credit_meta, head=raw_index < 6):
            continue
        if time_scale != 1.0 or time_shift:
            for c in chars:
                c["start"] = remap(c["start"])
                c["end"] = remap(c["end"])
            if chars[-1]["end"] <= 0:
                continue
            if max_time is not None and chars[0]["start"] >= max_time:
                continue

        tokens = analyze(text)
        if not tokens:
            continue
        _prefer_kana_lemma(tokens)
        if parsed.kind != "char":
            chars = _times_by_mora(text, remap(line["start"]),
                                   remap(line["end"]), tokens)
        enrich(tokens)

        words = []
        for t in tokens:
            seg_chars = chars[t["start"]:t["end"]]
            if not seg_chars:
                continue
            surface = t["surface"]
            w = {
                "text": surface,
                "lemma": t["lemma"],
                "pos": t["pos"],
                "pos1": t["pos1"],
                "start": seg_chars[0]["start"],
                "end": seg_chars[-1]["end"],
                "score": 1.0,
                "chars": seg_chars,
                "content": is_content(t),
            }
            if t.get("kana"):
                w["kana"] = t["kana"]
            w["romaji"] = "" if all(is_punct(c) for c in surface) else t["romaji"]
            if t.get("zh"):
                w["zh"] = t["zh"]
            if t.get("jlpt"):
                w["jlpt"] = t["jlpt"]
            if t.get("lemma_kana"):
                w["lemma_kana"] = t["lemma_kana"]
            words.append(w)

        if not words:
            continue

        seg = {
            "id": len(segments),
            "start": round(words[0]["start"], 3),
            "end": round(words[-1]["end"], 3),
            "text": text.strip(),
            "romaji": " ".join(w["romaji"] for w in words if w["romaji"]),
            "words": words,
        }
        zh = _match_translation(trans, seg["start"])
        if zh:
            seg["translation_zh"] = zh
        grammar = find_grammar(text, tokens)
        if grammar:
            seg["grammar"] = grammar
        segments.append(seg)

    duration = segments[-1]["end"] if segments else 0.0
    return {
        "meta": {
            "language": "ja",
            "duration_seconds": round(duration, 2),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            **meta,
        },
        "segments": segments,
    }


def from_plain_lines(lines: list[str], meta: dict,
                     translation: list[tuple[float, str]] | None = None) -> dict:
    """Build from bare text lines (used when only the words are known)."""
    parsed_lines = []
    for i, ln in enumerate(lines):
        parsed_lines.append({"start": float(i) * 4.0, "end": float(i) * 4.0 + 3.6,
                             "units": [(ln, float(i) * 4.0, float(i) * 4.0 + 3.6)]})
    return build(ParsedLyrics(lines=parsed_lines, translation=translation or [],
                             kind="line"), meta)


def slugify(text: str, fallback: str = "song") -> str:
    """ASCII-safe dataset folder name; keeps CJK so titles stay readable."""
    s = re.sub(r"[\\/:*?\"<>|\s]+", "-", text.strip())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return (s or fallback)[:60]
