"""5.5.3: finding and importing an older install's data."""
from __future__ import annotations

import json

import pytest

from app import legacy_import


def make_install(root, songs=("song-a", "song-b"), packs=True):
    data = root / "localdata"
    data.mkdir(parents=True)
    for name in songs:
        d = data / name
        d.mkdir()
        (d / "song_data.json").write_text(
            json.dumps({"meta": {"title": name}, "segments": []}), encoding="utf-8")
    if packs:
        (root / "models" / "whisper-small").mkdir(parents=True)
        (root / "models" / "whisper-small" / "model.bin").write_bytes(b"x" * 2048)
    (root / "backend" / "app").mkdir(parents=True)
    (root / "backend" / "app" / "version.py").write_text(
        'APP_VERSION = "1.3.0"\n', encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def no_real_drives(monkeypatch):
    """Drive-root scanning is for real users; tests must not see real installs."""
    monkeypatch.setattr(legacy_import, "_fixed_drives", lambda: [])


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    app = tmp_path / "UtaLearnNext"
    app.mkdir()
    monkeypatch.setattr(legacy_import, "APP_ROOT", app)
    monkeypatch.setattr(legacy_import, "DATA_DIR", app / "localdata")
    return app


class TestScan:
    def test_finds_a_sibling_install(self, workspace):
        make_install(workspace.parent / "UtaLearnNext-1.3.0" / "UtaLearnNext")
        found = legacy_import.candidates()
        assert len(found) == 1
        assert found[0]["songs"] == 2
        assert found[0]["version"] == "1.3.0"
        assert "models" in found[0]["packs"]

    def test_ignores_the_current_install(self, workspace):
        make_install(workspace)
        assert legacy_import.candidates() == []

    def test_ignores_a_folder_without_datasets(self, workspace):
        empty = workspace.parent / "other"
        (empty / "localdata" / "not-a-song").mkdir(parents=True)
        assert legacy_import.candidates() == []

    def test_finds_a_renamed_duplicate_folder(self, workspace):
        """Windows appends " (1)" when the user unzips a second copy."""
        make_install(workspace.parent / "UtaLearnNext-1.2.0 (1)" / "UtaLearnNext")
        found = legacy_import.candidates()
        assert len(found) == 1
        assert found[0]["songs"] == 2

    def test_finds_an_install_one_level_above(self, workspace):
        outer = workspace.parent / "old-root"
        outer.mkdir()
        make_install(outer / "UtaLearnNext-1.3.0")
        import shutil
        shutil.move(str(workspace), str(outer / "UtaLearnNext"))
        legacy_import.APP_ROOT = outer / "UtaLearnNext"
        legacy_import.DATA_DIR = outer / "UtaLearnNext" / "localdata"
        found = legacy_import.candidates()
        assert [f["path"] for f in found] == [str(outer / "UtaLearnNext-1.3.0")]

    def test_lists_song_names_for_the_prompt(self, workspace):
        make_install(workspace.parent / "old")
        assert legacy_import.candidates()[0]["song_names"] == ["song-a", "song-b"]

    def test_nested_labels_include_the_version_folder(self, workspace):
        """Four entries all read "UtaLearnNext" before; the wrapper identifies them."""
        make_install(workspace.parent / "UtaLearnNext-1.3.0" / "UtaLearnNext")
        assert legacy_import.candidates()[0]["label"] == "UtaLearnNext-1.3.0 / UtaLearnNext"

    def test_version_falls_back_to_the_folder_name(self, workspace):
        """v1.2/v1.3 packs shipped no version.py, so the folder is the only clue."""
        old = workspace.parent / "UtaLearnNext-1.3.0" / "UtaLearnNext"
        make_install(old)
        (old / "backend" / "app" / "version.py").unlink()
        assert legacy_import.candidates()[0]["version"] == "1.3.0"


class TestImport:
    def test_copies_datasets_and_packs(self, workspace):
        old = make_install(workspace.parent / "old")
        result = legacy_import.import_from(str(old))
        assert result["copied"] == 2
        assert (workspace / "localdata" / "song-a" / "song_data.json").is_file()
        assert (workspace / "models" / "whisper-small" / "model.bin").is_file()
        # a copy leaves the source in place
        assert (old / "localdata" / "song-a").is_dir()

    def test_never_overwrites_a_local_dataset(self, workspace):
        make_install(workspace / "localdata" / ".." if False else workspace.parent / "old")
        # this install already has song-a with newer content
        mine = workspace / "localdata" / "song-a"
        mine.mkdir(parents=True)
        (mine / "song_data.json").write_text('{"meta":{"title":"mine"}}',
                                             encoding="utf-8")
        result = legacy_import.import_from(str(workspace.parent / "old"))
        assert result["copied"] == 1
        assert result["skipped"] == 1
        body = json.loads((mine / "song_data.json").read_text(encoding="utf-8"))
        assert body["meta"]["title"] == "mine"

    def test_move_removes_the_source_datasets(self, workspace):
        old = make_install(workspace.parent / "old")
        legacy_import.import_from(str(old), move=True)
        assert not (old / "localdata" / "song-a").exists()
        assert (workspace / "localdata" / "song-a").is_dir()

    def test_a_folder_without_localdata_is_refused(self, workspace):
        other = workspace.parent / "no-data"
        other.mkdir()
        with pytest.raises(ValueError):
            legacy_import.import_from(str(other))

    def test_the_current_install_cannot_be_imported_into_itself(self, workspace):
        make_install(workspace)
        with pytest.raises(ValueError):
            legacy_import.import_from(str(workspace))

    def test_old_settings_carry_over_only_when_missing(self, workspace):
        old = make_install(workspace.parent / "old")
        (old / "localdata" / "settings.json").write_text(
            '{"proxy_mode":"manual"}', encoding="utf-8")
        result = legacy_import.import_from(str(old))
        assert "代理" in result["settings"]
        saved = json.loads(
            (workspace / "localdata" / "settings.json").read_text(encoding="utf-8"))
        assert saved["proxy_mode"] == "manual"

    def test_an_existing_settings_file_is_kept(self, workspace):
        old = make_install(workspace.parent / "old")
        (old / "localdata" / "settings.json").write_text(
            '{"proxy_mode":"manual"}', encoding="utf-8")
        (workspace / "localdata").mkdir(parents=True, exist_ok=True)
        (workspace / "localdata" / "settings.json").write_text(
            '{"proxy_mode":"off"}', encoding="utf-8")
        result = legacy_import.import_from(str(old))
        assert result["settings"] == ""
        saved = json.loads(
            (workspace / "localdata" / "settings.json").read_text(encoding="utf-8"))
        assert saved["proxy_mode"] == "off"
