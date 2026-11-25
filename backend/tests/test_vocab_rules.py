"""P1-5: both build pipelines must answer "is this a card?" the same way."""
from __future__ import annotations

from app import builder, fallback, vocab_rules
from app.sources import ParsedLyrics


def tok(surface: str, start: int, pos1: str = "名詞", lemma: str | None = None):
    # `is_content` requires a gloss: a word the dictionary cannot explain is
    # not worth a card either
    return {"surface": surface, "lemma": lemma or surface, "pos": "名词",
            "pos1": pos1, "kana": surface, "start": start,
            "end": start + len(surface), "romaji": surface, "zh": "释义"}


class TestContentFlag:
    def test_a_plain_noun_earns_a_card(self):
        assert vocab_rules.content_flag(tok("夢", 0)) is True

    def test_a_particle_never_does(self):
        assert vocab_rules.content_flag(tok("は", 0, "助詞")) is False

    def test_a_word_inside_a_pattern_does_not(self):
        spans = vocab_rules.grammar_spans(
            [{"at": 0, "matched": "わけにはいかない"}])
        assert vocab_rules.content_flag(tok("わけ", 0), spans) is False

    def test_a_word_outside_the_pattern_still_does(self):
        spans = vocab_rules.grammar_spans(
            [{"at": 5, "matched": "わけにはいかない"}])
        assert vocab_rules.content_flag(tok("夢", 0), spans) is True


def build_via_source():
    """One line through the timed-source path (builder)."""
    parsed = ParsedLyrics(
        lines=[{"start": 0.0, "end": 4.0,
                "units": [("夢を", 0.0, 1.0), ("見る", 1.0, 2.0)]}],
        kind="line",
    )
    data = builder.build(parsed, {"title": "t", "artist": "a"})
    return {w["text"]: w["content"] for w in data["segments"][0]["words"]}


class TestPipelinesAgree:
    def test_builder_marks_pattern_material_as_non_content(self):
        flags = build_via_source()
        # を is a particle in both pipelines
        assert flags.get("を", True) is False

    def test_both_use_the_shared_rule(self):
        """Neither module may keep its own copy of the rule."""
        for module in (builder, fallback):
            src = __import__("inspect").getsource(module)
            assert "is_content(" not in src.replace("from .dicts import", ""), (
                f"{module.__name__} still calls is_content directly")
