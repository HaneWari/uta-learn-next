"""Import a lyric file the user already has (5.3.2).

The online sources are private APIs that can disappear overnight, so there has
to be a fallback that does not need them:

    .qrc / .krc     per-character timing — reuse the existing decryptors
    enhanced LRC    `<mm:ss.xx>` word tags → per-character timing
    plain LRC       per-line timing → even sweep inside each line
    .txt            no timing at all → the custom-lyrics (whisper) path

Every format is normalised into the same `ParsedLyrics` the online sources
return, so `builder` never learns where the lyrics came from and the rest of
the pipeline stays single-path.
"""
from __future__ import annotations

import base64
import re
import zlib
from pathlib import Path

from app.sources import KRC_KEY, ParsedLyrics, _parse_krc_lines, _parse_lrc

SUPPORTED = {".qrc", ".krc", ".lrc", ".txt"}
MAX_BYTES = 4 * 1024 * 1024


class UnsupportedLyrics(ValueError):
    """Raised with a Chinese message the config page can show as-is."""


def sniff(name: str, data: bytes) -> str:
    """Decide the format from the file itself, not only the extension.

    People rename files, and a `.txt` that actually holds LRC is common; the
    content check makes the import "just work" instead of asking the user to
    classify their own file.
    """
    if len(data) > MAX_BYTES:
        raise UnsupportedLyrics(f"歌词文件超过 {MAX_BYTES // 1048576}MB")
    head = data[:4096]
    suffix = Path(name).suffix.lower()
    if head[:4] in (b"QRC\x00", b"\x00QRC"):
        return "qrc"
    if suffix == ".krc":
        return "krc"
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        raise UnsupportedLyrics("无法读取这个文件的文本内容") from None
    if suffix == ".qrc":
        # `<start,dur,0>` tags plus a .qrc name: KRC/QRC-style per-char body
        return "qrc" if re.search(r"<\d+,\d+,\d+>", text) else "qrc"
    if re.search(r"<\d{1,2}:\d{2}[.:]\d{1,3}>", text):
        # `<mm:ss.xx>` word tags are enhanced LRC, not KRC's `<start,dur,v>`
        return "char-line"
    if re.search(r"^\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]", text, re.M):
        return "lrc"
    if text.strip():
        return "text"
    raise UnsupportedLyrics("文件是空的")


def parse(name: str, data: bytes) -> ParsedLyrics:
    """Turn an uploaded lyric file into the shared intermediate shape."""
    kind = sniff(name, data)
    if kind == "qrc":
        return _parse_qrc_upload(data)
    if kind == "krc":
        return _parse_krc_upload(data)
    text = data.decode("utf-8-sig", errors="replace")
    if kind == "char-line":
        return ParsedLyrics(lines=_parse_enhanced_lrc(text), kind="char")
    if kind == "lrc":
        rows = _parse_lrc(text)
        if not rows:
            raise UnsupportedLyrics("这个 LRC 里没有可用的时间轴")
        return ParsedLyrics(lines=_lrc_lines(rows), kind="line")
    raise UnsupportedLyrics(
        "这个文件没有时间轴。纯文本歌词请用「自定义歌词」模式，"
        "由 whisper 在音频上自动对齐。")


def _parse_qrc_upload(data: bytes) -> ParsedLyrics:
    from app.qrc_des import qrc_decrypt
    from app.sources import _parse_qrc_lines

    text = data.decode("utf-8", errors="replace")
    if "[" not in text:
        # encrypted QRC: the payload starts with the QRC magic, not plain text
        try:
            text = qrc_decrypt(text)
        except Exception:  # noqa: BLE001
            raise UnsupportedLyrics("无法解密这个 QRC 文件") from None
    lines = _parse_qrc_lines(text)
    if not lines:
        raise UnsupportedLyrics("这个 QRC 里没有逐字时间轴")
    return ParsedLyrics(lines=lines, kind="char")


def _parse_krc_upload(data: bytes) -> ParsedLyrics:
    # KRC files start with a short magic (usually `krc1`), then an XOR + zlib
    # body. The magic length is not worth trusting: try plain text first, then
    # each plausible header length, and take whatever decompresses.
    text = ""
    for skip in (4, 3, 0):
        body = data[skip:]
        try:
            plain = bytes(b ^ KRC_KEY[i % len(KRC_KEY)]
                          for i, b in enumerate(body))
            text = zlib.decompress(plain).decode("utf-8", errors="replace")
            break
        except (zlib.error, ValueError):
            continue
    if not text:
        text = data.decode("utf-8", errors="replace")
    lines = _parse_krc_lines(text)
    if not lines:
        raise UnsupportedLyrics("这个 KRC 里没有逐字时间轴")
    return ParsedLyrics(lines=lines, kind="char")


LRC_WORD_TAG = re.compile(r"<(\d{1,2}):(\d{2})[.:](\d{1,3})>([^<]*)")
LRC_LINE_TAG = re.compile(r"^\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\](.*)$")


def _seconds(minutes: str, seconds: str, frac: str | None) -> float:
    value = int(minutes) * 60 + int(seconds)
    if frac:
        value += int(frac.ljust(3, "0")[:3]) / 1000.0
    return value


def _parse_enhanced_lrc(text: str) -> list[dict]:
    """`[00:12.00]<00:12.00>夢<00:12.40>を` → per-character units."""
    out = []
    for raw in text.splitlines():
        lm = LRC_LINE_TAG.match(raw.strip())
        if not lm:
            continue
        line_start = _seconds(lm.group(1), lm.group(2), lm.group(3))
        body = lm.group(4)
        tags = list(LRC_WORD_TAG.finditer(body))
        if not tags:
            continue
        units = []
        for i, m in enumerate(tags):
            start = _seconds(m.group(1), m.group(2), m.group(3))
            end = (
                _seconds(tags[i + 1].group(1), tags[i + 1].group(2),
                         tags[i + 1].group(3))
                if i + 1 < len(tags)
                else start + 0.3
            )
            piece = m.group(4)
            if piece.strip():
                units.append((piece, start, max(end, start + 0.05)))
        if units:
            out.append({
                "start": line_start,
                "end": max(units[-1][2], line_start + 0.5),
                "units": units,
            })
    if not out:
        raise UnsupportedLyrics("这个增强 LRC 里没有 <mm:ss.xx> 逐字标签")
    return out


def _lrc_lines(rows: list[tuple[float, str]]) -> list[dict]:
    """Plain LRC → one unit per line, so the builder spreads the sweep."""
    out = []
    for i, (start, body) in enumerate(rows):
        end = rows[i + 1][0] if i + 1 < len(rows) else start + max(2.0, len(body) * 0.2)
        out.append({"start": start, "end": max(end, start + 0.4),
                    "units": [(body, start, max(end, start + 0.4))]})
    return out


def decode_text(data: bytes) -> str:
    """Best-effort text for the `.txt` → custom-lyrics hand-off."""
    for encoding in ("utf-8-sig", "utf-16", "gb18030", "shift_jis"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def looks_like_base64(text: str) -> bool:
    """KRC/QRC dumps pasted as text are often base64-wrapped."""
    try:
        base64.b64decode(text, validate=True)
        return len(text) > 64
    except (ValueError, TypeError):
        return False
