"""Export presets, clip validation and the API surface around them."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main
from app import export


@pytest.fixture
def client():
    return TestClient(main.app, base_url="http://127.0.0.1:8000")


class TestPresets:
    def test_three_presets_all_at_60fps(self):
        assert set(export.PRESETS) == {"landscape", "portrait", "4k"}
        assert export.FPS == 60

    def test_portrait_is_taller_than_wide(self):
        p = export.PRESETS["portrait"]
        assert p["height"] > p["width"]

    def test_4k_doubles_the_scale_not_the_layout(self):
        fourk = export.PRESETS["4k"]
        landscape = export.PRESETS["landscape"]
        assert fourk["scale"] == 2
        assert (fourk["width"], fourk["height"]) == (
            landscape["width"],
            landscape["height"],
        )

    def test_an_unknown_preset_falls_back(self):
        assert export.preset("nope") is export.PRESETS[export.DEFAULT_PRESET]

    def test_estimate_grows_with_length_and_resolution(self):
        short = export.estimate_seconds(60, "landscape", 3)
        long_clip = export.estimate_seconds(300, "landscape", 3)
        fourk = export.estimate_seconds(60, "4k", 3)
        assert long_clip > short
        assert fourk > short

    def test_more_pages_shorten_the_estimate(self):
        assert export.estimate_seconds(120, "landscape", 4) < export.estimate_seconds(
            120, "landscape", 1
        )


class TestPresetsApi:
    def test_lists_the_presets_with_pixel_sizes(self, client):
        body = client.get("/api/export/presets").json()
        assert body["fps"] == 60
        ids = {p["id"] for p in body["presets"]}
        assert ids == {"landscape", "portrait", "4k"}
        fourk = next(p for p in body["presets"] if p["id"] == "4k")
        assert (fourk["width_px"], fourk["height_px"]) == (3840, 2160)


class TestEnvCheck:
    """§5.4.2: the recorder component must not gate the default path."""

    def test_a_missing_recorder_no_longer_fails_the_probe(self, monkeypatch):
        monkeypatch.setattr(export, "pick_browser", lambda *a, **k: ("chrome.exe", ""))
        monkeypatch.setattr(export, "probe_record_video", lambda *a, **k: (False, "no ffmpeg"))
        monkeypatch.setattr(export.binaries, "find", lambda name: "ffmpeg")
        env = export.env_check()
        assert env["ok"] is True
        assert env["state"] == "ok"
        # still reported, because 兼容模式 needs it
        assert env["checks"]["compat_ready"] is False

    def test_a_missing_browser_still_fails(self, monkeypatch):
        monkeypatch.setattr(export, "pick_browser", lambda *a, **k: (None, "boom"))
        monkeypatch.setattr(export.binaries, "find", lambda name: "ffmpeg")
        assert export.env_check()["state"] == "no_browser"

    def test_a_missing_ffmpeg_still_fails(self, monkeypatch):
        monkeypatch.setattr(export, "pick_browser", lambda *a, **k: ("chrome.exe", ""))
        monkeypatch.setattr(export.binaries, "find", lambda name: None)
        assert export.env_check()["state"] == "no_ffmpeg"


class TestClipValidation:
    def test_a_short_clip_is_rejected(self, client, make_song):
        make_song("song")
        r = client.post("/api/export", json={
            "song": "song", "clip_start": 10, "clip_end": 10.2,
        })
        assert r.status_code == 400
        assert "1 秒" in r.json()["detail"]

    def test_an_unknown_song_is_404(self, client, data_dir):
        r = client.post("/api/export", json={"song": "nope"})
        assert r.status_code == 404
