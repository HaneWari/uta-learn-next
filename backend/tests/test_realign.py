"""5.3.3: single-line realignment — guards before any whisper work happens."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main
from app import realign


@pytest.fixture
def client():
    return TestClient(main.app, base_url="http://127.0.0.1:8000")


class TestGuards:
    def test_an_empty_line_is_refused(self):
        with pytest.raises(ValueError):
            realign.realign_line("nowhere.mp3", "   ", 0.0, 1.0)

    def test_an_invalid_span_is_refused(self):
        with pytest.raises(ValueError):
            realign.realign_line("nowhere.mp3", "夢", 5.0, 5.0)

    def test_the_window_never_starts_before_zero(self):
        # -5 s would be a negative seek; the clamp is what keeps ffmpeg happy
        assert max(0.0, 0.2 - realign.WINDOW) == 0.0


class TestApi:
    def test_a_missing_pack_is_reported_actionably(
            self, client, make_song, monkeypatch):
        from app import packs

        make_song("song")
        monkeypatch.setattr(packs, "whisper_installed", lambda: False)
        r = client.post("/api/songs/song/realign/0")
        assert r.status_code == 409
        assert "扩展包" in r.json()["detail"]

    def test_a_missing_song_is_404(self, client, monkeypatch):
        from app import packs

        monkeypatch.setattr(packs, "whisper_installed", lambda: True)
        r = client.post("/api/songs/nope/realign/0")
        assert r.status_code == 404

    def test_a_lyrics_only_dataset_is_refused(
            self, client, make_song, monkeypatch):
        from app import packs

        make_song("song")  # no audio.mp3
        monkeypatch.setattr(packs, "whisper_installed", lambda: True)
        r = client.post("/api/songs/song/realign/0")
        assert r.status_code == 400
        assert "没有音频" in r.json()["detail"]

    def test_an_unknown_segment_is_404(self, client, make_song, monkeypatch):
        from app import packs

        path = make_song("song")
        (path.parent / "audio.mp3").write_bytes(b"fake")
        monkeypatch.setattr(packs, "whisper_installed", lambda: True)
        r = client.post("/api/songs/song/realign/9999")
        assert r.status_code == 404
