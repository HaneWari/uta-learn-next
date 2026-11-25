"""Search parallelism, ordering and per-source error reporting."""
from __future__ import annotations

import time

import pytest

from app import sources


class FakeSource:
    def __init__(self, hits=None, error: str | None = None, delay: float = 0.0):
        self.hits = hits or []
        self.error = error
        self.delay = delay

    def search(self, _query: str):
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise RuntimeError(self.error)
        # the real sources hand back `Song` objects, not dicts
        return [sources.Song(**h) for h in self.hits]


def song(name: str, duration: float, kind: str = "char", source: str = "qq") -> dict:
    return {"source": source, "id": name, "title": name, "artist": "a",
            "album": "", "duration": duration, "kind": kind, "extra": {}}


@pytest.fixture
def three_sources(monkeypatch):
    table = {
        "qq": FakeSource([song("q1", 200), song("q2", 100)]),
        "kugou": FakeSource([song("k1", 100.5, source="kugou")]),
        "lrclib": FakeSource([song("l1", 260, kind="line", source="lrclib")]),
    }
    monkeypatch.setattr(sources, "SOURCES", table)
    return table


class TestSearchAll:
    def test_all_sources_are_merged(self, three_sources):
        results, errors, statuses = sources.search_all("x", audio_duration=100)
        assert len(results) == 4
        assert errors == []
        assert statuses == {"qq": "ok", "kugou": "ok", "lrclib": "ok"}

    def test_sources_run_concurrently(self, monkeypatch):
        table = {f"s{i}": FakeSource([], delay=0.4) for i in range(3)}
        monkeypatch.setattr(sources, "SOURCES", table)
        start = time.time()
        sources.search_all("x")
        elapsed = time.time() - start
        assert elapsed < 0.9, f"三个 0.4s 的源串行跑了 {elapsed:.1f}s"

    def test_one_failing_source_does_not_hide_the_others(self, monkeypatch):
        monkeypatch.setattr(sources, "SOURCES", {
            "qq": FakeSource([song("q", 10)]),
            "kugou": FakeSource(error="连接超时"),
            "lrclib": FakeSource([]),
        })
        results, errors, statuses = sources.search_all("x")
        assert [r["title"] for r in results] == ["q"]
        assert errors == [{"source": "kugou", "error": "连接超时"}]
        assert statuses == {"qq": "ok", "kugou": "error", "lrclib": "empty"}

    def test_a_slow_source_times_out(self, monkeypatch):
        monkeypatch.setattr(sources, "SEARCH_TIMEOUT", 0.2)
        monkeypatch.setattr(sources, "SOURCES", {
            "qq": FakeSource([song("q", 10)]),
            "kugou": FakeSource([song("k", 10)], delay=1.5),
        })
        results, errors, statuses = sources.search_all("x")
        assert [r["title"] for r in results] == ["q"]
        assert statuses["kugou"] == "error"
        assert "超时" in errors[0]["error"]

    def test_named_subset_only_queries_those_sources(self, three_sources):
        _, _, statuses = sources.search_all("x", names=["qq"])
        assert statuses == {"qq": "ok"}

    def test_empty_source_list_returns_nothing(self, monkeypatch):
        monkeypatch.setattr(sources, "SOURCES", {})
        assert sources.search_all("x") == ([], [], {})


class TestSortResults:
    def test_duration_mode_puts_the_closest_first(self):
        rows = [song("far", 300), song("near", 103), song("exact", 100)]
        ordered = sources.sort_results(rows, "duration", audio_duration=100)
        assert [r["title"] for r in ordered] == ["exact", "near", "far"]

    def test_duration_mode_prefers_per_char_on_a_tie(self):
        rows = [song("line", 100, kind="line"), song("char", 100, kind="char")]
        ordered = sources.sort_results(rows, "duration", audio_duration=100)
        assert [r["title"] for r in ordered] == ["char", "line"]

    def test_char_mode_ignores_the_audio_length_order(self):
        rows = [song("near-line", 100, kind="line"), song("far-char", 400, kind="char")]
        ordered = sources.sort_results(rows, "char", audio_duration=100)
        assert [r["title"] for r in ordered] == ["far-char", "near-line"]

    def test_source_mode_groups_qq_then_kugou_then_lrclib(self):
        rows = [song("l", 100, source="lrclib"), song("k", 300, source="kugou"),
                song("q", 500, source="qq")]
        ordered = sources.sort_results(rows, "source", audio_duration=100)
        assert [r["source"] for r in ordered] == ["qq", "kugou", "lrclib"]

    def test_duration_mode_without_audio_degrades_to_char(self):
        rows = [song("line", 100, kind="line"), song("char", 900, kind="char")]
        ordered = sources.sort_results(rows, "duration", audio_duration=0)
        assert [r["title"] for r in ordered] == ["char", "line"]

    def test_close_hits_get_a_duration_match_badge(self):
        rows = [song("near", 101.5), song("far", 120)]
        ordered = sources.sort_results(rows, "duration", audio_duration=100)
        assert [r["duration_match"] for r in ordered] == [True, False]

    def test_no_audio_means_no_badges(self):
        rows = [song("a", 100)]
        ordered = sources.sort_results(rows, "char", audio_duration=0)
        assert ordered[0]["duration_match"] is False

    def test_an_unknown_mode_falls_back_to_duration(self):
        rows = [song("far", 300), song("near", 101)]
        ordered = sources.sort_results(rows, "nonsense", audio_duration=100)
        assert [r["title"] for r in ordered] == ["near", "far"]


class TestProxyLifetime:
    def test_a_proxy_change_rebuilds_the_client(self, monkeypatch):

        src = sources.LrclibSource()
        seen = []
        monkeypatch.setattr(sources, "resolve_proxy", lambda: seen[-1] if seen else None)
        seen.append("http://a:1")
        first = src.client
        seen.append("http://b:2")
        second = src.client
        assert first is not second
        assert second is src.client

    def test_the_same_proxy_reuses_the_pool(self):
        src = sources.LrclibSource()
        assert src.client is src.client
