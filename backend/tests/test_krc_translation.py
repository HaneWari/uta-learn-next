"""P1-7: Kugou's `[language:...]` block carries the translation."""
from __future__ import annotations

import base64

from app.sources import _parse_krc_translation


def krc_body(rows: list[tuple[int, str]]) -> str:
    return "\n".join(f"[{start},1000]{text}" for start, text in rows)


def payload(translation: str | None) -> str:
    head = "[id:$00000000]\n[ar:artist]\n[ti:title]\n"
    lyrics = "[1000,2000]<0,500,0>夢<500,500,0>を"
    if translation is None:
        return head + lyrics + "\n"
    encoded = base64.b64encode(translation.encode("utf-8")).decode()
    return head + lyrics + f"\n[language:{encoded}]\n"


class TestKrcTranslation:
    def test_reads_timed_translation_lines(self):
        body = krc_body([(1000, "把梦想"), (3000, "看见")])
        got = _parse_krc_translation(payload(body))
        assert got == [(1.0, "把梦想"), (3.0, "看见")]

    def test_no_block_means_no_translation(self):
        assert _parse_krc_translation(payload(None)) == []

    def test_a_malformed_block_is_ignored(self):
        text = "[1000,2000]<0,500,0>夢\n[language:!!!not-base64!!!]\n"
        assert _parse_krc_translation(text) == []

    def test_unit_tags_are_stripped_from_the_translation(self):
        body = "[1000,900]<0,300,0>把<300,300,0>梦想"
        got = _parse_krc_translation(payload(body))
        assert got == [(1.0, "把梦想")]

    def test_blank_translation_lines_are_dropped(self):
        body = krc_body([(1000, "  "), (2000, "有字")])
        assert _parse_krc_translation(payload(body)) == [(2.0, "有字")]
