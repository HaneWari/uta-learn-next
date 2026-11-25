"""Pure-function coverage for the NLP layer (no network, no ffmpeg)."""
from __future__ import annotations

import pytest

from app.dicts import (
    analyze,
    apply_reading_marks,
    enrich,
    is_content,
    parse_reading_marks,
    restyle_long_vowel,
    to_romaji,
)


class TestRomaji:
    @pytest.mark.parametrize("kana, expected", [
        ("あいうえお", "aiueo"),
        ("がっこう", "gakkou"),          # sokuon doubles the next consonant
        ("きょう", "kyou"),              # youon
        ("しゃしん", "shashin"),
        ("とうきょう", "toukyou"),        # long vowel stays "ou"
        ("を", "o"),                     # object particle already reads o
        ("ん", "n"),
    ])
    def test_kana(self, kana, expected):
        assert to_romaji(kana) == expected

    def test_katakana_is_normalised(self):
        assert to_romaji("テスト") == "tesuto"


class TestLongVowel:
    @pytest.mark.parametrize("style, expected", [
        ("ou", "toukyou"),
        ("macron", "tōkyō"),
        ("oo", "tookyoo"),
    ])
    def test_styles(self, style, expected):
        assert restyle_long_vowel("toukyou", style) == expected

    def test_short_vowels_are_untouched(self):
        assert restyle_long_vowel("sakura", "macron") == "sakura"

    def test_empty_input(self):
        assert restyle_long_vowel("", "oo") == ""


class TestReadingMarks:
    def test_halfwidth_brackets(self):
        plain, marks = parse_reading_marks("[明日](あす)が来る")
        assert plain == "明日が来る"
        assert marks == [{"base": "明日", "kana": "あす", "at": 0}]

    def test_fullwidth_brackets(self):
        plain, marks = parse_reading_marks("【今日】（きょう）は晴れ")
        assert plain == "今日は晴れ"
        assert marks[0]["base"] == "今日"
        assert marks[0]["kana"] == "きょう"

    def test_romaji_reading_is_converted_to_kana(self):
        _, marks = parse_reading_marks("[明日](asu)")
        assert marks[0]["kana"] == "あす"

    def test_mixed_width_pair(self):
        plain, marks = parse_reading_marks("[今日]（きょう）")
        assert plain == "今日"
        assert marks[0]["kana"] == "きょう"

    @pytest.mark.parametrize("text", [
        "明日(あす)",        # bare base — not a mark, sung as written
        "[明日]が来る",      # bracket with no reading
        "[明日](あす",       # unbalanced
        "(あす)[明日]",      # paren first
    ])
    def test_non_mark_shapes_stay_text(self, text):
        plain, marks = parse_reading_marks(text)
        assert plain == text
        assert marks == []

    def test_mark_inside_text_keeps_offsets(self):
        plain, marks = parse_reading_marks("君は[明日](あす)も")
        assert plain == "君は明日も"
        assert marks[0]["at"] == 2

    def test_apply_overwrites_kana_and_romaji_only(self):
        plain, marks = parse_reading_marks("[明日](あす)会おう")
        tokens = analyze(plain)
        before = [(t["start"], t["end"]) for t in tokens]
        apply_reading_marks(plain, tokens, marks)
        assert tokens[0]["kana"] == "あす"
        assert tokens[0]["romaji"] == "asu"
        assert [(t["start"], t["end"]) for t in tokens] == before


class TestEnrich:
    def test_particle_keeps_both_readings(self):
        toks = enrich(analyze("東京へ行こう"))
        particle = next(t for t in toks if t["surface"] == "へ")
        # literal: へ = he; pronunciation: へ = e
        assert particle["romaji_literal"] == "he"
        assert particle["pron"] == "え"
        assert particle["romaji"] == "e"

    def test_a_content_word_has_identical_readings(self):
        toks = enrich(analyze("東京"))
        assert toks[0]["romaji"] == toks[0]["romaji_literal"]
        assert toks[0]["kana_literal"] == toks[0]["kana"]

    def test_topic_particle_wa(self):
        toks = enrich(analyze("私は学生"))
        particle = next(t for t in toks if t["surface"] == "は")
        assert particle["romaji_literal"] == "ha"
        assert particle["romaji"] == "wa"

    def test_particle_is_not_glossed_as_a_noun_homograph(self):
        # ほら is an interjection in a lyric but 洞 (cave) is a homograph in the
        # dictionary; the gloss must follow the POS the tagger picked.
        tokens = enrich(analyze("ほら"))
        assert tokens[0]["pos1"] == "感動詞"
        gloss = tokens[0].get("zh") or ""
        assert "洞" not in gloss
        assert "喂" in gloss or not gloss

    def test_content_words_get_gloss_and_level(self):
        tokens = enrich(analyze("明日の学校"))
        school = [t for t in tokens if t["surface"] == "学校"]
        assert school and school[0].get("zh")
        assert is_content(school[0])

    def test_every_token_gets_romaji(self):
        tokens = enrich(analyze("コトは誰も"))
        assert all(t.get("romaji") for t in tokens)
