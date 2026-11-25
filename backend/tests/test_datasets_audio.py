"""Dataset audio file naming and MIME selection (P1-3)."""
from __future__ import annotations

import pytest

from app import datasets


class TestFindAudio:
    def test_prefers_a_browser_format(self, tmp_path):
        (tmp_path / "audio.flac").write_bytes(b"x")
        (tmp_path / "audio.mp3").write_bytes(b"y")
        found = datasets.find_audio(tmp_path)
        assert found is not None
        assert found.name in ("audio.flac", "audio.mp3")

    def test_returns_none_for_a_lyrics_only_dataset(self, tmp_path):
        assert datasets.find_audio(tmp_path) is None

    def test_legacy_audio_mp3_is_still_found(self, tmp_path):
        (tmp_path / "audio.mp3").write_bytes(b"x")
        assert datasets.find_audio(tmp_path).name == "audio.mp3"


class TestAudioMime:
    @pytest.mark.parametrize("name, expected", [
        ("audio.mp3", "audio/mpeg"),
        ("audio.m4a", "audio/mp4"),
        ("audio.flac", "audio/flac"),
        ("audio.wav", "audio/wav"),
        ("audio.opus", "audio/ogg"),
    ])
    def test_mime_matches_the_real_format(self, name, expected):
        from pathlib import Path

        assert datasets.audio_mime(Path(name)) == expected

    def test_unknown_extension_is_octet_stream(self):
        from pathlib import Path

        assert datasets.audio_mime(Path("audio.xyz")) == "application/octet-stream"


class TestSaveDataset:
    def test_keeps_the_real_extension_and_records_it(self, tmp_path, monkeypatch):
        monkeypatch.setattr(datasets, "DATA_DIR", tmp_path)
        src = tmp_path / "in.flac"
        src.write_bytes(b"fake-flac")
        out = datasets.save_dataset("song", {"meta": {}, "segments": []}, src)
        assert (out / "audio.flac").exists()
        assert not (out / "audio.mp3").exists()
        import json

        meta = json.loads((out / "song_data.json").read_text(encoding="utf-8"))["meta"]
        assert meta["audio_file"] == "audio.flac"
        assert meta["has_audio"] is True

    def test_a_lyrics_only_dataset_records_no_audio(self, tmp_path, monkeypatch):
        monkeypatch.setattr(datasets, "DATA_DIR", tmp_path)
        out = datasets.save_dataset("song", {"meta": {}, "segments": []}, None)
        import json

        meta = json.loads((out / "song_data.json").read_text(encoding="utf-8"))["meta"]
        assert meta["has_audio"] is False
        assert "audio_file" not in meta
