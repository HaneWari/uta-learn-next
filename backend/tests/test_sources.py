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


@pytest.fixture(autouse=True)
def no_search_cache(monkeypatch):
    """The 24h cache lives on disk; a test must never see another test's hits."""
    monkeypatch.setattr(sources.search_cache, "get", lambda *a, **k: None)
    monkeypatch.setattr(sources.search_cache, "put", lambda *a, **k: None)


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
    def test_the_closest_hit_comes_first(self):
        rows = [song("far", 300), song("near", 103), song("exact", 100)]
        ordered = sources.sort_results(rows, audio_duration=100)
        assert [r["title"] for r in ordered] == ["exact", "near", "far"]

    def test_a_per_char_hit_beats_a_line_hit_of_the_same_length(self):
        rows = [song("line", 100, kind="line"), song("char", 100, kind="char")]
        ordered = sources.sort_results(rows, audio_duration=100)
        assert [r["title"] for r in ordered] == ["char", "line"]

    def test_only_close_per_char_hits_jump_the_queue(self):
        rows = [
            song("far-char", 400, kind="char"),
            song("near-line", 100, kind="line"),
            song("near-char", 101, kind="char"),
        ]
        ordered = sources.sort_results(rows, audio_duration=100)
        # near-char is the only "will actually line up" hit; the other two keep
        # the fixed duration order
        assert [r["title"] for r in ordered] == ["near-char", "near-line", "far-char"]

    def test_without_audio_per_char_hits_come_first(self):
        rows = [song("line", 100, kind="line"), song("char", 900, kind="char")]
        ordered = sources.sort_results(rows, audio_duration=0)
        assert [r["title"] for r in ordered] == ["char", "line"]

    def test_each_group_is_sorted_by_duration_ascending(self):
        rows = [song("b", 300), song("a", 200), song("c", 400)]
        ordered = sources.sort_results(rows, audio_duration=2000)
        assert [r["title"] for r in ordered] == ["a", "b", "c"]

    def test_hits_without_a_duration_sort_last(self):
        rows = [song("unknown", 0), song("known", 500)]
        ordered = sources.sort_results(rows, audio_duration=0)
        assert [r["title"] for r in ordered] == ["known", "unknown"]

    def test_close_hits_get_a_duration_match_badge(self):
        rows = [song("near", 101.5), song("far", 120)]
        ordered = sources.sort_results(rows, audio_duration=100)
        assert [r["duration_match"] for r in ordered] == [True, False]

    def test_no_audio_means_no_badges(self):
        rows = [song("a", 100)]
        ordered = sources.sort_results(rows, audio_duration=0)
        assert ordered[0]["duration_match"] is False


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


class TestQQSearch:
    """QQ's mobile search CGI started returning 2001 for nearly every request.

    The legacy CGI answers the same query, so search must try it first and only
    fall back to the mobile call. These tests pin that order: a regression that
    flips it makes every QQ search fail in production while unit tests still
    pass, which is exactly how this shipped broken.
    """

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, legacy):
            self.legacy = legacy
            self.calls = []

        def close(self):
            return None

        def get(self, url, params=None, headers=None):
            self.calls.append(("get", url, params))
            return self.legacy

        def post(self, url, content=None):
            self.calls.append(("post", url, None))
            raise RuntimeError("mobile CGI must not be reached")

    def _legacy_payload(self, rows):
        return {"code": 0, "data": {"song": {"list": rows}}}

    @pytest.fixture(autouse=True)
    def no_proxy(self, monkeypatch):
        """Keep the source from rebuilding its client against the real network."""
        monkeypatch.setattr(sources, "resolve_proxy", lambda: None)

    def test_search_uses_the_legacy_cgi_first(self):
        src = sources.QQSource()
        client = self.FakeClient(self.FakeResponse(self._legacy_payload([
            {"songmid": "003WFMXk4O5ywc", "songid": 247294300, "songname": "夜に駆ける",
             "interval": 261, "albumname": "THE BOOK",
             "singer": [{"name": "YOASOBI"}]},
        ])))
        src._client = client
        src._client_proxy = None
        found = src.search("夜に駆ける")
        assert client.calls[0][0] == "get"
        assert client.calls[0][1] == sources.QQ_SEARCH_URL
        assert found[0].id == "247294300"
        assert found[0].extra["mid"] == "003WFMXk4O5ywc"
        assert found[0].duration == 261

    def test_an_empty_legacy_result_is_an_error_for_the_caller(self):
        src = sources.QQSource()
        src._client = self.FakeClient(self.FakeResponse(self._legacy_payload([])))
        src._client_proxy = None
        with pytest.raises(RuntimeError):
            src._search_legacy("nothing")
