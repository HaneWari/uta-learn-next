"""The 24h search cache: scope, expiry and the "all failed" guard."""
from __future__ import annotations

import pytest

from app import search_cache


@pytest.fixture(autouse=True)
def temp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(search_cache, "CACHE_FILE", tmp_path / "search.json")
    yield


HIT = [{"source": "qq", "title": "夜に駆ける"}]


class TestRoundTrip:
    def test_a_miss_returns_none(self):
        assert search_cache.get("nothing") is None

    def test_a_hit_comes_back_intact(self):
        search_cache.put("夜に駆ける", None, HIT, [], {"qq": "ok"})
        got = search_cache.get("夜に駆ける")
        assert got is not None
        results, errors, statuses = got
        assert results == HIT
        assert errors == []
        assert statuses == {"qq": "ok"}

    def test_the_query_is_normalised(self):
        search_cache.put("  Night ", None, HIT, [], {"qq": "ok"})
        assert search_cache.get("night") is not None

    def test_the_source_set_is_part_of_the_key(self):
        search_cache.put("x", ["qq"], HIT, [], {"qq": "ok"})
        assert search_cache.get("x", ["kugou"]) is None

    def test_source_order_does_not_matter(self):
        search_cache.put("x", ["qq", "kugou"], HIT, [], {"qq": "ok"})
        assert search_cache.get("x", ["kugou", "qq"]) is not None


class TestExpiry:
    def test_older_than_a_day_is_a_miss(self):
        import time

        now = time.time()
        search_cache.put("x", None, HIT, [], {"qq": "ok"}, now=now)
        assert search_cache.get("x", now=now + 23 * 3600) is not None
        assert search_cache.get("x", now=now + 25 * 3600) is None

    def test_an_all_failed_search_is_not_cached(self):
        search_cache.put(
            "x", None, [], [{"source": "qq", "error": "boom"}], {"qq": "error"})
        assert search_cache.get("x") is None

    def test_a_partial_failure_is_cached(self):
        search_cache.put("x", None, HIT, [{"source": "kugou", "error": "boom"}],
                         {"qq": "ok", "kugou": "error"})
        assert search_cache.get("x") is not None


class TestClear:
    def test_clear_empties_the_file(self):
        search_cache.put("x", None, HIT, [], {"qq": "ok"})
        assert search_cache.clear() == 1
        assert search_cache.get("x") is None

    def test_a_corrupt_file_reads_as_empty(self):
        search_cache.CACHE_FILE.write_text("{nope", encoding="utf-8")
        assert search_cache.get("x") is None
