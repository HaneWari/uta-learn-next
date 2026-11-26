"""设置 → 扩展包:真实体积,以及安装/删除的实际动作。"""
from __future__ import annotations

from fastapi.testclient import TestClient

import main
from app import packs


def test_status_reports_both_packs_with_sizes(monkeypatch, tmp_path):
    monkeypatch.setattr(packs, "APP_ROOT", tmp_path)
    whisper = tmp_path / "models" / "whisper-small"
    whisper.mkdir(parents=True)
    (whisper / "model.bin").write_bytes(b"x" * 2048)
    translate = tmp_path / "models" / "translate-ja-zh"
    translate.mkdir(parents=True)
    (translate / "model.bin").write_bytes(b"y" * 1024)

    client = TestClient(main.app, base_url="http://127.0.0.1")
    body = client.get("/api/packs/status").json()
    assert [p["key"] for p in body["packs"]] == ["custom_lyrics", "chromium"]
    custom = body["packs"][0]
    assert custom["installed"] is True
    assert custom["size"] == 3072
    assert body["packs"][1]["installed"] is False
    assert body["packs"][1]["size"] == 0


def test_delete_removes_only_that_pack(monkeypatch, tmp_path):
    monkeypatch.setattr(packs, "APP_ROOT", tmp_path)
    (tmp_path / "models" / "whisper-small").mkdir(parents=True)
    (tmp_path / "models" / "whisper-small" / "model.bin").write_bytes(b"x")
    (tmp_path / "localdata" / "song").mkdir(parents=True)
    (tmp_path / "localdata" / "song" / "song_data.json").write_text("{}", encoding="utf-8")

    client = TestClient(main.app, base_url="http://127.0.0.1")
    r = client.delete("/api/packs/custom_lyrics")
    assert r.status_code == 200
    assert r.json()["removed"] is True
    assert not (tmp_path / "models").exists()
    # user data is never touched by a pack delete
    assert (tmp_path / "localdata" / "song" / "song_data.json").exists()


def test_deleting_a_missing_pack_is_a_conflict(monkeypatch, tmp_path):
    monkeypatch.setattr(packs, "APP_ROOT", tmp_path)
    client = TestClient(main.app, base_url="http://127.0.0.1")
    assert client.delete("/api/packs/chromium").status_code == 409
    assert client.delete("/api/packs/nope").status_code == 404


def test_remove_never_touches_a_global_playwright_cache(monkeypatch, tmp_path):
    """PLAYWRIGHT_BROWSERS_PATH may point outside the app; 删除 must not."""
    global_cache = tmp_path / "global-cache"
    (global_cache / "chromium-1").mkdir(parents=True)
    monkeypatch.setattr(packs, "APP_ROOT", tmp_path / "app")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(global_cache))

    assert packs.remove("browsers") is False
    assert (global_cache / "chromium-1").exists()
