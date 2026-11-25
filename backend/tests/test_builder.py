"""Dataset-building helpers that do not need audio."""
from __future__ import annotations

import pytest

from app.builder import _is_credit, _squeeze, build, slugify
from app.sources import ParsedLyrics


class TestSlugify:
    @pytest.mark.parametrize("raw, expected", [
        ("時の流れに身をまかせ", "時の流れに身をまかせ"),
        ("A/B: C?", "A-B-C"),
        ("  spaced  out  ", "spaced-out"),
        ("", "song"),
    ])
    def test_slug(self, raw, expected):
        assert slugify(raw) == expected

    def test_length_is_capped(self):
        assert len(slugify("あ" * 200)) <= 60


class TestCredits:
    @pytest.mark.parametrize("line", [
        "作詞：山田太郎", "作曲：山田", "編曲：鈴木", "Lyrics: Someone",
        "Music: Someone",
    ])
    def test_credit_lines(self, line):
        assert _is_credit(line, {"title": "x", "artist": "y"})

    def test_title_only_counts_at_the_head(self):
        meta = {"title": "時の流れに身をまかせ", "artist": "桂銀淑"}
        assert _is_credit("時の流れに身をまかせ", meta, head=True)
        # a chorus repeating the title later is a real lyric
        assert not _is_credit("時の流れに身をまかせ", meta, head=False)

    def test_squeeze_strips_spaces_and_case(self):
        assert _squeeze(" Hello  世界 ") == "hello世界"


class TestBuildFromLines:
    def test_line_dataset_shape(self):
        parsed = ParsedLyrics(
            lines=[
                {"units": [("こんにちは", 0.0, 2.0)], "start": 0.0, "end": 2.0},
                {"units": [("さようなら", 2.0, 4.0)], "start": 2.0, "end": 4.0},
            ],
            translation=[(0.0, "你好")],
            kind="line",
        )
        data = build(parsed, {"title": "t", "artist": "a", "duration_seconds": 4.0})
        assert data["meta"]["title"] == "t"
        assert len(data["segments"]) == 2
        seg = data["segments"][0]
        assert seg["text"] == "こんにちは"
        assert seg["translation_zh"] == "你好"
        assert seg["words"] and seg["words"][0]["start"] == pytest.approx(0.0)
        # per-glyph timings must cover the line
        assert seg["words"][0].get("chars")
