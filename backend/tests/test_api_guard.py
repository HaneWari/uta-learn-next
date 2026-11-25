"""Regression tests for the local-API security boundary.

Anyone who can reach 127.0.0.1:8000 can delete songs, install extension packs
and even run pip. A page in the user's browser can do all of that too unless the
server refuses foreign origins and Host headers, so these tests guard a security
property, not just plumbing.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main


def make_client() -> TestClient:
    # the real app is only reached over loopback, so a legitimate request always
    # carries 127.0.0.1 — TestClient's default "testserver" host is not one
    return TestClient(main.app, base_url="http://127.0.0.1:8000")


@pytest.fixture
def client():
    return make_client()


class TestCors:
    def test_no_wildcard_allow_origin(self, client):
        r = client.options(
            "/api/songs/x",
            headers={"Origin": "https://evil.example",
                     "Access-Control-Request-Method": "DELETE"},
        )
        assert r.headers.get("access-control-allow-origin") != "*"
        assert r.headers.get("access-control-allow-origin") is None

    def test_foreign_origin_cannot_write(self, client):
        r = client.post("/api/search", json={"query": "テスト"},
                        headers={"Origin": "https://evil.example"})
        assert r.status_code == 403

    def test_foreign_origin_cannot_delete(self, client):
        r = client.delete("/api/songs/whatever",
                          headers={"Origin": "https://evil.example"})
        assert r.status_code == 403

    def test_null_origin_is_rejected(self, client):
        # sandboxed iframes and file:// pages send `Origin: null`
        r = client.post("/api/search", json={"query": "テスト"},
                        headers={"Origin": "null"})
        assert r.status_code == 403

    def test_local_origin_is_fine(self, client):
        r = client.delete("/api/songs/does-not-exist",
                          headers={"Origin": "http://127.0.0.1:8000"})
        # the guard let it through; the route itself says "unknown song"
        assert r.status_code == 404


class TestHostHeader:
    @pytest.mark.parametrize("host", [
        "attacker.example", "attacker.example:8000", "evil.test",
    ])
    def test_foreign_host_blocked(self, client, host):
        r = client.get("/api/songs", headers={"Host": host})
        assert r.status_code == 403

    @pytest.mark.parametrize("host", [
        "127.0.0.1:8000", "127.0.0.1", "localhost:8000", "[::1]:8000",
    ])
    def test_local_host_allowed(self, client, host, monkeypatch):
        monkeypatch.setattr(main.guard, "DEV", True)
        r = client.get("/api/songs", headers={"Host": host})
        assert r.status_code == 200


class TestToken:
    def test_writes_need_the_token_outside_dev(self, client, monkeypatch):
        monkeypatch.setattr(main.guard, "DEV", False)
        r = client.post("/api/search", json={"query": "テスト"})
        assert r.status_code == 403
        assert "token" in r.text

    def test_wrong_token_is_rejected(self, client, monkeypatch):
        monkeypatch.setattr(main.guard, "DEV", False)
        r = client.post("/api/search", json={"query": "テスト"},
                        headers={"X-Uta-Token": "nope"})
        assert r.status_code == 403

    def test_right_token_passes(self, client, monkeypatch):
        monkeypatch.setattr(main.guard, "DEV", False)
        r = client.delete("/api/songs/does-not-exist",
                          headers={"X-Uta-Token": main.TOKEN})
        assert r.status_code == 404

    def test_reads_stay_open(self, client, monkeypatch):
        monkeypatch.setattr(main.guard, "DEV", False)
        assert client.get("/api/songs").status_code == 200


class TestTokenInjection:
    def test_index_carries_the_token(self, client, tmp_path, monkeypatch):
        (tmp_path / "index.html").write_text(
            "<!doctype html><html><head><title>x</title></head>"
            "<body><div id=root></div></body></html>", encoding="utf-8")
        monkeypatch.setattr(main, "DIST_DIR", tmp_path)
        r = client.get("/")
        assert r.status_code == 200
        assert f'name="uta-token" content="{main.TOKEN}"' in r.text

    def test_index_is_not_cached(self, client, tmp_path, monkeypatch):
        (tmp_path / "index.html").write_text("<html><head></head></html>",
                                             encoding="utf-8")
        monkeypatch.setattr(main, "DIST_DIR", tmp_path)
        assert client.get("/").headers["cache-control"].startswith("no-store")
