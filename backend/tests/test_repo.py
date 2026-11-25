"""SongRepo is the only writer of song_data.json — these tests pin its promises.
Concurrent stage edits used to be read-modify-write with no lock, so a fast
double edit (or two tabs) silently dropped one save, and a crash mid-write could
truncate the file and lose every card and lyric edit of that song.
"""
from __future__ import annotations

import json
import threading

import pytest

from app import repo


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class TestRead:
    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            repo.read(tmp_path / "song_data.json")

    def test_v1_is_migrated_in_memory(self, tmp_path):
        path = tmp_path / "song_data.json"
        path.write_text(json.dumps({
            "meta": {"title": "t", "whisperx_model": "small", "align_model": "m"},
            "segments": [],
        }), encoding="utf-8")
        data = repo.read(path)
        assert data["schema_version"] == repo.SCHEMA_VERSION
        assert data["meta"]["title"] == "t"          # untouched
        assert data["meta"]["revision"] == 0
        # reading never rewrites the file
        assert "schema_version" not in read_json(path)

    def test_broken_file_does_not_hide_the_backup(self, tmp_path):
        path = tmp_path / "song_data.json"
        (tmp_path / "song_data.json.bak").write_text(
            json.dumps({"meta": {"title": "backup"}, "segments": []}),
            encoding="utf-8")
        path.write_text("{not json", encoding="utf-8")
        data = repo.read(path)
        assert data["meta"]["title"] == "backup"

    def test_newer_schema_is_refused(self, tmp_path):
        path = tmp_path / "song_data.json"
        path.write_text(json.dumps({"schema_version": repo.SCHEMA_VERSION + 1,
                                    "meta": {}, "segments": []}), encoding="utf-8")
        with pytest.raises(repo.SchemaTooNew):
            repo.read(path)


class TestUpdate:
    def test_bumps_revision_and_keeps_a_backup(self, tmp_path):
        path = tmp_path / "song_data.json"
        path.write_text(json.dumps({"meta": {}, "segments": []}), encoding="utf-8")
        before = path.read_text(encoding="utf-8")

        data = repo.update(path, lambda d: d["meta"].__setitem__("time_offset", 0.5))
        assert data["meta"]["time_offset"] == 0.5
        assert data["meta"]["revision"] == 1
        assert read_json(path)["meta"]["revision"] == 1
        # the pre-update file survives as .bak
        bak = (tmp_path / "song_data.json.bak").read_text(encoding="utf-8")
        assert json.loads(bak) == json.loads(before)
        # no temp file left behind
        assert not (tmp_path / "song_data.json.tmp").exists()

    def test_stale_revision_is_a_conflict(self, tmp_path):
        path = tmp_path / "song_data.json"
        path.write_text(json.dumps({"meta": {"revision": 3}, "segments": []}),
                        encoding="utf-8")
        with pytest.raises(repo.RevisionConflict) as err:
            repo.update(path, lambda d: None, expected_revision=2)
        assert err.value.current == 3
        # nothing was written
        assert read_json(path)["meta"]["revision"] == 3

    def test_matching_revision_passes(self, tmp_path):
        path = tmp_path / "song_data.json"
        path.write_text(json.dumps({"meta": {"revision": 3}, "segments": []}),
                        encoding="utf-8")
        assert repo.update(path, lambda d: None, expected_revision=3)["meta"]["revision"] == 4

    def test_a_raising_mutator_leaves_the_file_alone(self, tmp_path):
        path = tmp_path / "song_data.json"
        original = json.dumps({"meta": {}, "segments": [{"id": 0}]})
        path.write_text(original, encoding="utf-8")

        def boom(_data):
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            repo.update(path, boom)
        assert path.read_text(encoding="utf-8") == original
        assert not (tmp_path / "song_data.json.tmp").exists()

    def test_concurrent_updates_are_not_lost(self, tmp_path):
        path = tmp_path / "song_data.json"
        path.write_text(json.dumps({"meta": {"seen": []}, "segments": []}),
                        encoding="utf-8")

        workers, per_worker = 8, 5

        def bump(i):
            for j in range(per_worker):
                repo.update(path, lambda d, i=i, j=j: d["meta"]["seen"].append((i, j)))

        threads = [threading.Thread(target=bump, args=(i,)) for i in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        data = read_json(path)
        assert len(data["meta"]["seen"]) == workers * per_worker
        assert data["meta"]["revision"] == workers * per_worker


class TestWriteNew:
    def test_new_dataset_is_stamped(self, tmp_path):
        path = tmp_path / "song_data.json"
        repo.write_new(path, {"meta": {"title": "t"}, "segments": []})
        data = read_json(path)
        assert data["schema_version"] == repo.SCHEMA_VERSION
        assert data["meta"]["revision"] == 0

    def test_parent_dirs_are_created(self, tmp_path):
        path = tmp_path / "a" / "b" / "song_data.json"
        repo.write_new(path, {"meta": {}, "segments": []})
        assert path.exists()
