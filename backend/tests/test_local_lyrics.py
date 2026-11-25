"""5.3.2: local lyric import — format sniffing and normalisation."""
from __future__ import annotations

import zlib

import pytest
from fastapi.testclient import TestClient

import main
from app import local_lyrics
from app.sources import KRC_KEY

PLAIN_LRC = """[ti:テスト]
[00:01.00]夢を見る
[00:05.50]夜を越えて
"""

ENHANCED_LRC = """[00:01.00]<00:01.00>夢<00:01.40>を<00:01.80>見る
[00:05.00]<00:05.00>夜<00:05.50>を
"""


class TestSniff:
    def test_plain_lrc(self):
        assert local_lyrics.sniff("a.lrc", PLAIN_LRC.encode()) == "lrc"

    def test_enhanced_lrc_by_content(self):
        assert local_lyrics.sniff("a.lrc", ENHANCED_LRC.encode()) == "char-line"

    def test_a_txt_that_holds_lrc_is_treated_as_lrc(self):
        assert local_lyrics.sniff("lyrics.txt", PLAIN_LRC.encode()) == "lrc"

    def test_pure_text_goes_to_the_custom_mode(self):
        assert local_lyrics.sniff("a.txt", "夢を見る\n夜を越えて\n".encode()) == "text"

    def test_krc_extension(self):
        assert local_lyrics.sniff("a.krc", b"\x00\x00\x00\x00rest") == "krc"

    def test_an_empty_file_is_rejected(self):
        with pytest.raises(local_lyrics.UnsupportedLyrics):
            local_lyrics.sniff("a.txt", b"   ")

    def test_an_oversized_file_is_rejected(self):
        with pytest.raises(local_lyrics.UnsupportedLyrics):
            local_lyrics.sniff("a.lrc", b"x" * (local_lyrics.MAX_BYTES + 1))


class TestParse:
    def test_plain_lrc_becomes_one_unit_per_line(self):
        parsed = local_lyrics.parse("a.lrc", PLAIN_LRC.encode())
        assert parsed.kind == "line"
        assert len(parsed.lines) == 2
        assert parsed.lines[0]["units"][0][0] == "夢を見る"
        assert parsed.lines[0]["start"] == pytest.approx(1.0)

    def test_enhanced_lrc_keeps_per_character_timing(self):
        parsed = local_lyrics.parse("a.lrc", ENHANCED_LRC.encode())
        assert parsed.kind == "char"
        units = parsed.lines[0]["units"]
        assert [u[0] for u in units] == ["夢", "を", "見る"]
        assert units[0][1] == pytest.approx(1.0)
        assert units[1][1] == pytest.approx(1.4)

    def test_plain_text_asks_for_the_custom_mode(self):
        with pytest.raises(local_lyrics.UnsupportedLyrics) as err:
            local_lyrics.parse("a.txt", "夢を見る\n".encode())
        assert "自定义歌词" in str(err.value)

    def test_a_lrc_without_timestamps_is_rejected(self):
        with pytest.raises(local_lyrics.UnsupportedLyrics):
            local_lyrics.parse("a.lrc", b"[ti:only tags]\n")

    def test_krc_bytes_are_decrypted(self):
        body = "[1000,2000]<0,500,0>夢<500,500,0>を".encode()
        # the real order is compress-then-XOR (see KugouSource.fetch)
        packed = zlib.compress(body)
        xored = bytes(b ^ KRC_KEY[i % len(KRC_KEY)] for i, b in enumerate(packed))
        raw = b"\x00\x00\x00\x00" + xored
        parsed = local_lyrics.parse("a.krc", raw)
        assert parsed.kind == "char"
        assert "".join(u[0] for u in parsed.lines[0]["units"]) == "夢を"


class TestUploadApi:
    @pytest.fixture
    def client(self):
        return TestClient(main.app, base_url="http://127.0.0.1:8000")

    def test_preview_returns_lines_and_a_token(self, client):
        r = client.post("/api/uploads/lyrics",
                        files={"file": ("a.lrc", PLAIN_LRC.encode(), "text/plain")})
        assert r.status_code == 200
        body = r.json()
        assert body["lines"] == 2
        assert body["kind"] == "line"
        assert len(body["token"]) == 12
        assert body["preview"][0]["text"] == "夢を見る"

    def test_a_plain_text_file_is_refused_with_guidance(self, client):
        r = client.post("/api/uploads/lyrics",
                        files={"file": ("a.txt", "夢を見る\n".encode(), "text/plain")})
        assert r.status_code == 400
        assert "自定义歌词" in r.json()["detail"]

    def test_a_bad_token_is_rejected(self, client, make_song):
        r = client.post("/api/build-local", json={
            "lyrics_token": "zzzz", "upload_id": "000000000000"})
        assert r.status_code == 400
