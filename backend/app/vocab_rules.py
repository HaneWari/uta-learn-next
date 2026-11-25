"""Shared "does this token earn a card?" rule.

The two build pipelines used to answer that question differently: the
timed-source path (`builder`) marked a token with `is_content()` alone, while
the whisper path (`fallback`) also dropped tokens sitting inside a detected
grammar pattern — わけ in わけにはいかない is grammar, not vocabulary. The same
song therefore produced a different card row depending on which mode built it,
which reads as a bug.

Both callers now go through `content_flag`, so there is one answer.
"""
from __future__ import annotations

from app.dicts import is_content


def grammar_spans(grammar: list[dict]) -> list[tuple[int, int]]:
    """Character ranges covered by detected patterns."""
    return [(g["at"], g["at"] + len(g["matched"])) for g in grammar]


def in_spans(token: dict, spans: list[tuple[int, int]]) -> bool:
    return any(token["start"] < end and start < token["end"]
               for start, end in spans)


def content_flag(token: dict, spans: list[tuple[int, int]] | None = None) -> bool:
    """True when this token is worth a vocabulary card.

    `spans` are the grammar patterns found in the same line. A token inside one
    is part of the pattern and gets the grammar card instead of a word card —
    unless the token *spans* the whole pattern, in which case it is the pattern.
    """
    if not is_content(token):
        return False
    if not spans:
        return True
    return not in_spans(token, spans)
