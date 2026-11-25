"""End-to-end behaviour of the song routes over TestClient."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client():
    return TestClient(main.app, base_url="http://127.0.0.1:8000")


class TestGetSong:
    def test_returns_migrated_data(self, client, make_song):
        path = make_song("song")
        r = client.get("/api/songs/song")
        assert r.status_code == 200
        body = r.json()
        assert body["schema_version"] == 2
        assert body["meta"]["revision"] == 0
        # the file on disk is untouched until someone edits it
        assert "schema_version" not in json.loads(path.read_text(encoding="utf-8"))

    def test_unknown_song(self, client, data_dir):
        assert client.get("/api/songs/nope").status_code == 404

    def test_newer_schema_is_refused(self, client, make_song):
        path = make_song("song")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["schema_version"] = 99
        path.write_text(json.dumps(data), encoding="utf-8")
        r = client.get("/api/songs/song")
        assert r.status_code == 409
        assert "升级" in r.json()["detail"]


class TestPatchSegment:
    def test_edit_is_saved_and_revision_bumped(self, client, make_song):
        path = make_song("song")
        r = client.patch("/api/songs/song", json={
            "id": 0, "vocab_override": {"hide": [1]},
        })
        assert r.status_code == 200
        assert r.json()["vocab_override"] == {"hide": [1]}
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["meta"]["revision"] == 1
        assert saved["segments"][0]["vocab_override"] == {"hide": [1]}

    def test_stale_if_match_is_a_conflict(self, client, make_song):
        make_song("song")
        client.patch("/api/songs/song", json={"id": 0, "hidden": True})
        r = client.patch("/api/songs/song", json={"id": 0, "hidden": False},
                         headers={"If-Match": "0"})
        assert r.status_code == 409
        assert "刷新" in r.json()["detail"]

    def test_current_if_match_passes(self, client, make_song):
        make_song("song")
        client.patch("/api/songs/song", json={"id": 0, "hidden": True})
        r = client.patch("/api/songs/song", json={"id": 0, "hidden": False},
                         headers={"If-Match": "1"})
        assert r.status_code == 200

    def test_bad_if_match(self, client, make_song):
        make_song("song")
        r = client.patch("/api/songs/song", json={"id": 0, "hidden": True},
                         headers={"If-Match": "abc"})
        assert r.status_code == 400

    def test_unknown_segment(self, client, make_song):
        make_song("song")
        r = client.patch("/api/songs/song", json={"id": 42, "hidden": True})
        assert r.status_code == 404

    def test_read_only_fields_are_refused(self, client, make_song):
        make_song("song")
        r = client.patch("/api/songs/song", json={"id": 0, "text": "書き換え"})
        assert r.status_code == 400

    def test_lyric_override_is_retokenised(self, client, make_song):
        make_song("song")
        r = client.patch("/api/songs/song", json={
            "id": 0, "lyric_override": {"text": "[明日](あす)会おう"},
        })
        assert r.status_code == 200
        ov = r.json()["lyric_override"]
        assert ov["words"], "an edited line must keep furigana/romaji/wipe"
        assert "".join(w["text"] for w in ov["words"]) == "明日会おう"
        assert ov["words"][0]["kana"] == "あす"


class TestPatchMeta:
    def test_time_offset_roundtrip(self, client, make_song):
        path = make_song("song")
        r = client.patch("/api/songs/song", json={"time_offset": 0.4})
        assert r.status_code == 200
        assert r.json()["time_offset"] == 0.4
        assert json.loads(path.read_text(encoding="utf-8"))["meta"]["time_offset"] == 0.4

    def test_zero_removes_the_key(self, client, make_song):
        path = make_song("song")
        client.patch("/api/songs/song", json={"time_offset": 0.4})
        client.patch("/api/songs/song", json={"time_offset": 0})
        assert "time_offset" not in json.loads(path.read_text(encoding="utf-8"))["meta"]

    @pytest.mark.parametrize("value", [2.5, -3, "abc"])
    def test_out_of_range_is_rejected(self, client, make_song, value):
        make_song("song")
        assert client.patch("/api/songs/song",
                            json={"time_offset": value}).status_code == 400

    def test_trans_hidden(self, client, make_song):
        make_song("song")
        assert client.patch("/api/songs/song",
                            json={"trans_hidden": True}).json()["trans_hidden"] is True
        assert client.patch("/api/songs/song",
                            json={"trans_hidden": False}).json()["trans_hidden"] is False
