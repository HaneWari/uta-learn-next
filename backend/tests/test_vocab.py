"""The personal word book: de-duplication, ordering and scoped deletes."""
from __future__ import annotations

import pytest

from app import vocab


@pytest.fixture(autouse=True)
def temp_file(tmp_path, monkeypatch):
    monkeypatch.setattr(vocab, "VOCAB_FILE", tmp_path / "_vocab.json")
    yield


def entry(text="夢", song="song", seg=1, **kw):
    base = {"song": song, "segment_id": seg, "text": text, "zh": "梦"}
    base.update(kw)
    return base


class TestAdd:
    def test_stores_a_complete_record(self):
        rec = vocab.add(entry(kana="ゆめ", romaji="yume", jlpt="N3", line="夢を"))
        assert rec["text"] == "夢"
        assert rec["kana"] == "ゆめ"
        assert rec["added_at"] > 0
        assert len(vocab.list_all()) == 1

    def test_the_same_word_from_the_same_line_updates_in_place(self):
        first = vocab.add(entry(zh="梦"))
        second = vocab.add(entry(zh="梦想"))
        assert len(vocab.list_all()) == 1
        assert second["zh"] == "梦想"
        assert second["added_at"] == first["added_at"]

    def test_the_same_word_from_two_songs_is_two_entries(self):
        vocab.add(entry(song="a"))
        vocab.add(entry(song="b"))
        assert len(vocab.list_all()) == 2

    def test_a_missing_word_is_rejected(self):
        with pytest.raises(ValueError):
            vocab.add(entry(text="   "))

    def test_a_missing_song_is_rejected(self):
        with pytest.raises(ValueError):
            vocab.add(entry(song=""))


class TestList:
    def test_newest_first(self):
        vocab.add(entry(text="一"))
        vocab.add(entry(text="二", seg=2))
        assert [i["text"] for i in vocab.list_all()][0] == "二"

    def test_filter_by_song(self):
        vocab.add(entry(song="a"))
        vocab.add(entry(song="b", seg=2))
        assert [i["song"] for i in vocab.list_all("a")] == ["a"]

    def test_counts_per_song(self):
        vocab.add(entry(song="a", seg=1))
        vocab.add(entry(song="a", seg=2, text="空"))
        vocab.add(entry(song="b", seg=3, text="海"))
        assert vocab.count_by_song() == {"a": 2, "b": 1}

    def test_a_corrupt_file_reads_as_empty(self):
        vocab.VOCAB_FILE.write_text("{nope", encoding="utf-8")
        assert vocab.list_all() == []


class TestRemove:
    def test_removes_one_entry(self):
        vocab.add(entry())
        assert vocab.remove("song", 1, "夢") is True
        assert vocab.list_all() == []

    def test_missing_entry_reports_false(self):
        assert vocab.remove("song", 1, "夢") is False

    def test_clear_is_scoped_to_one_song(self):
        vocab.add(entry(song="a"))
        vocab.add(entry(song="b", seg=2))
        assert vocab.clear("a") == 1
        assert [i["song"] for i in vocab.list_all()] == ["b"]

    def test_clear_all(self):
        vocab.add(entry(song="a"))
        vocab.add(entry(song="b", seg=2))
        assert vocab.clear() == 2
