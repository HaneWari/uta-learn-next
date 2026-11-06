"""Fit a source lyric timeline onto the user's own audio file.

The problem
-----------
A lyric source times its characters against the *release* recording. The file
the user has is often not that recording: an intro trimmed off, a TV-size cut,
a remaster running a hair faster. Hand-trimming cannot fix this, because the
two timelines differ by an unknown shift *and* an unknown scale.

The approach
------------
Whisper the user's audio to get word anchors, align the source's lyric lines to
those anchors with the same monotonic DP used for the whisper fallback, and fit

    t_user = a + b * t_source

through the matched pairs. ``a`` absorbs the offset (a trimmed intro), ``b``
absorbs a speed difference. A robust fit (Theil–Sen: median of pairwise slopes)
ignores the handful of lines whisper mishears.

``b`` is kept only when it is too large to be an artefact of whisper's drifting
onset bias (see MIN_SLOPE / MIN_DRIFT); otherwise the mapping degrades to a pure
offset, which is both the common case and the more accurate one.

The result is applied to the source's *per-character* timestamps, so the
precision of the source survives — unlike re-aligning the text from scratch,
which throws it away.
"""
from __future__ import annotations

import os
from statistics import median

from .fallback import align

# Whisper's word onsets land consistently early on sung audio (measured at
# -0.49s median against per-character reference timings on two songs; word ends
# are far worse at -1.36s, midpoints -0.90s). Anchoring on the word start is
# still the best choice, and this constant removes the residual lead so the
# highlight does not light up before the singing starts.
ONSET_LEAD = float(os.environ.get("UTALEARN_ONSET_LEAD", "0.45"))

# A fitted slope is only worth applying when it is large enough that whisper's
# own onset bias cannot explain it. Measured on real audio (braveheart with its
# first 20s cut, where the truth is b == 1): the bias drift alone produced a
# spurious b = 0.99582, i.e. 0.605s of drift across the song -- and that free
# fit actually had a *lower* RMS residual than an offset-only fit, so no
# goodness-of-fit test can tell a real tempo change from bias drift. Hence a
# prior instead: below these thresholds the offset-only model wins.
MIN_SLOPE = 0.006   # 0.6% tempo difference
MIN_DRIFT = 1.2     # seconds of drift accumulated across the song


def _line_text(line: dict) -> str:
    return "".join(u[0] for u in (line.get("units") or []))


def _theil_sen(pairs: list[tuple[float, float]]) -> tuple[float, float]:
    """Median-of-slopes line fit; insensitive to a few bad anchors."""
    slopes = []
    for i in range(len(pairs)):
        xi, yi = pairs[i]
        for j in range(i + 1, len(pairs)):
            xj, yj = pairs[j]
            dx = xj - xi
            # a slope needs real horizontal separation, and a plausible ratio:
            # a lyric line never runs at a wildly different tempo
            if abs(dx) >= 4.0:
                k = (yj - yi) / dx
                if 0.85 <= k <= 1.18:
                    slopes.append(k)
    b = median(slopes) if slopes else 1.0
    a = median(y - b * x for x, y in pairs)
    return a, b


def _refine(pairs: list[tuple[float, float]], a: float, b: float,
            keep: float = 1.6) -> tuple[float, float, list[tuple[float, float]]]:
    """Drop anchors the first fit could not explain, then fit again.

    Whisper mishears a line now and then; those anchors are the ones with a big
    residual. With only a handful of lines, a single bad anchor can tilt the
    slope, so it is worth one cleaning pass.
    """
    inliers = [(x, y) for x, y in pairs if abs(a + b * x - y) <= keep]
    if len(inliers) < 4 or len(inliers) == len(pairs):
        return a, b, pairs
    a2, b2 = _theil_sen(inliers)
    if not (0.85 <= b2 <= 1.18):
        return a, b, pairs
    return a2, b2, inliers


def fit(parsed, wsegs: list[dict]) -> dict | None:
    """Estimate (a, b) mapping source time to the user's audio timeline.

    Returns None when there are not enough reliable anchors to trust.
    """
    lines = [_line_text(ln) for ln in parsed.lines]
    if len(lines) < 4 or len(wsegs) < 4:
        return None

    placed = align(lines, wsegs)

    # Anchor on the first *word* of each matched whisper segment: a segment
    # start usually includes the breath before the phrase, which would bias the
    # offset early. (Anchoring on both ends as well made the fit worse in
    # practice — whisper's phrase ends drift late by more than its starts drift
    # early, so the two do not cancel.)
    pairs: list[tuple[float, float]] = []
    for line, hit in zip(parsed.lines, placed):
        if hit is None:
            continue
        words = hit.get("words") or []
        y = float(words[0]["s"]) if words else float(hit["start"])
        pairs.append((float(line["start"]), y))

    if len(pairs) < 4:
        return None

    a, b = _theil_sen(pairs)
    if not (0.85 <= b <= 1.18):
        return None
    a, b, used = _refine(pairs, a, b)

    # Only keep the slope when it is too large to be bias drift (see MIN_SLOPE /
    # MIN_DRIFT above); otherwise fall back to a pure offset, which is both the
    # far more common real-world case (a trimmed intro) and immune to drift.
    span = max(x for x, _ in used) - min(x for x, _ in used)
    if abs(b - 1.0) < MIN_SLOPE or abs(b - 1.0) * span < MIN_DRIFT:
        b = 1.0
        a = median(y - x for x, y in used)

    spread = median([y for _, y in used]) or 1.0
    resid = median([abs(a + b * x - y) for x, y in used])

    # whisper reports the onset before the singer actually starts
    a += ONSET_LEAD

    return {
        "a": round(a, 3),
        "b": round(b, 5),
        "anchors": len(used),
        "residual": round(resid, 3),
        "ok": resid <= max(0.9, 0.035 * spread),
    }


def describe(fit_result: dict) -> str:
    """Human-readable summary for the job log."""
    a, b = fit_result["a"], fit_result["b"]
    parts = []
    if abs(a) >= 0.2:
        parts.append(f"起点偏移 {a:+.2f}s")
    if abs(b - 1.0) >= 0.002:
        parts.append(f"速度差 {(b - 1.0) * 100:+.2f}%")
    body = "、".join(parts) if parts else "时间轴基本一致"
    return f"{body}（{fit_result['anchors']} 个锚点，残差 {fit_result['residual']:.2f}s）"
