"""Update decision, staging and rollback — no network, no real releases."""
from __future__ import annotations

import json
import zipfile

import pytest

from app import updater


@pytest.fixture(autouse=True)
def temp_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "STAGING", tmp_path / "_update")
    monkeypatch.setattr(updater, "BACKUP", tmp_path / "app.prev")
    monkeypatch.setattr(updater, "APP_ROOT", tmp_path / "app")
    (tmp_path / "app").mkdir()
    yield


class TestVersions:
    @pytest.mark.parametrize("a, b, newer", [
        ("2.0.1", "2.0.0", True),
        ("2.1.0", "2.0.9", True),
        ("2.0.0", "2.0.0", False),
        ("1.9.0", "2.0.0", False),
        # numeric comparison only: a prerelease of the same version is not a
        # newer build, and no release here ships prereleases
        ("2.0.0", "2.0.0-beta", False),
        ("2.0.1-beta", "2.0.0", True),
    ])
    def test_is_newer(self, a, b, newer):
        assert updater.is_newer(a, b) is newer


class TestDecide:
    def manifest(self, **kw):
        base = {
            "version": "2.0.1",
            "runtime_id": "abc",
            "patch": {"name": "UtaLearnNext-2.0.1-patch.zip", "sha256": "00"},
            "full": {"name": "UtaLearnNext-2.0.1.zip", "sha256": "11"},
        }
        base.update(kw)
        return base

    def test_same_runtime_offers_a_patch(self):
        d = updater.decide(self.manifest(), runtime_id="abc")
        assert d["available"] is True
        assert d["kind"] == "patch"
        assert d["runtime_changed"] is False
        assert d["asset"]["name"].endswith("-patch.zip")

    def test_a_changed_runtime_offers_the_full_package(self):
        d = updater.decide(self.manifest(), runtime_id="different")
        assert d["kind"] == "full"
        assert d["runtime_changed"] is True
        assert not d["asset"]["name"].endswith("-patch.zip")

    def test_the_same_version_is_not_available(self):
        d = updater.decide(self.manifest(version="2.0.0"), runtime_id="abc")
        assert d["available"] is False
        assert d["kind"] is None

    def test_an_unknown_local_runtime_never_reports_a_patch(self):
        d = updater.decide(self.manifest(), runtime_id="")
        assert d["kind"] == "full"

    def test_the_asset_carries_the_target_version(self):
        d = updater.decide(self.manifest(), runtime_id="abc")
        assert d["asset"]["version"] == "2.0.1"


def make_patch(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, body in members.items():
            z.writestr(name, body)


class TestStagePatch:
    def test_only_app_layer_paths_are_extracted(self, tmp_path):
        zip_path = tmp_path / "p.zip"
        make_patch(zip_path, {
            "backend/main.py": "new",
            "frontend/dist/index.html": "html",
            "python/python.exe": "MUST NOT LAND",
            "localdata/song/song_data.json": "user data",
            "models/whisper-small/model.bin": "big",
        })
        pending = updater.stage_patch(zip_path)
        assert (pending / "backend" / "main.py").read_text(encoding="utf-8") == "new"
        assert (pending / "frontend" / "dist" / "index.html").exists()
        assert not (pending / "python").exists()
        assert not (pending / "localdata").exists()
        assert not (pending / "models").exists()

    def test_a_pack_without_the_app_layer_is_rejected(self, tmp_path):
        zip_path = tmp_path / "p.zip"
        make_patch(zip_path, {"readme.txt": "nothing useful"})
        with pytest.raises(RuntimeError):
            updater.stage_patch(zip_path)

    def test_traversal_members_are_skipped(self, tmp_path):
        zip_path = tmp_path / "p.zip"
        make_patch(zip_path, {
            "backend/../../escape.txt": "nope",
            "backend/ok.txt": "yes",
        })
        pending = updater.stage_patch(zip_path)
        assert (pending / "backend" / "ok.txt").exists()
        assert not (tmp_path / "escape.txt").exists()


class TestApplyAndRollback:
    def _prepare(self, tmp_path):
        app = tmp_path / "app"
        (app / "backend").mkdir(parents=True)
        (app / "backend" / "main.py").write_text("old", encoding="utf-8")
        (app / "frontend" / "dist").mkdir(parents=True)
        (app / "frontend" / "dist" / "index.html").write_text("old", encoding="utf-8")
        pending = updater.STAGING / "pending"
        (pending / "backend").mkdir(parents=True)
        (pending / "backend" / "main.py").write_text("new", encoding="utf-8")
        (pending / "frontend" / "dist").mkdir(parents=True)
        (pending / "frontend" / "dist" / "index.html").write_text("new", encoding="utf-8")
        updater.mark_pending("2.0.1")
        return app

    def test_apply_swaps_both_layers(self, tmp_path):
        app = self._prepare(tmp_path)
        version = updater.apply_pending()
        assert version == "2.0.1"
        assert (app / "backend" / "main.py").read_text(encoding="utf-8") == "new"
        assert (app / "frontend" / "dist" / "index.html").read_text(encoding="utf-8") == "new"

    def test_apply_is_a_no_op_without_a_staged_patch(self):
        assert updater.apply_pending() is None

    def test_rollback_restores_the_previous_layer(self, tmp_path):
        app = self._prepare(tmp_path)
        updater.apply_pending()
        assert updater.rollback() is True
        assert (app / "backend" / "main.py").read_text(encoding="utf-8") == "old"

    def test_rollback_without_a_backup_reports_false(self):
        assert updater.rollback() is False

    def test_pending_version_disappears_after_apply(self, tmp_path):
        self._prepare(tmp_path)
        assert updater.pending_version() == "2.0.1"
        updater.apply_pending()
        assert updater.pending_version() is None


class TestLocalRuntimeId:
    def test_reads_build_info(self, tmp_path, monkeypatch):
        (tmp_path / "BUILD_INFO.json").write_text(
            json.dumps({"runtime_id": "deadbeef"}), encoding="utf-8")
        monkeypatch.setattr(updater, "APP_ROOT", tmp_path)
        assert updater.local_runtime_id() == "deadbeef"

    def test_missing_build_info_is_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(updater, "APP_ROOT", tmp_path)
        assert updater.local_runtime_id() == ""
