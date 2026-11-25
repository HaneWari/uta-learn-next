"""Dataset helpers (naming, listing, `m:ss` parsing)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.datasets import dataset, list_datasets, mmss


class TestMmss:
    @pytest.mark.parametrize("raw, expected", [
        ("1:30", 90.0), ("0:05", 5.0), (12.5, 12.5), ("42", 42.0),
        ("", 0.0), (None, 0.0), ("nope", 0.0), ("-3", 0.0), ("1:x", 0.0),
    ])
    def test_parse(self, raw, expected):
        assert mmss(raw) == pytest.approx(expected)


class TestDatasetGuard:
    @pytest.mark.parametrize("name", ["../etc", "a/b", "a\\b", ".hidden", "_uploads"])
    def test_bad_names_rejected(self, name):
        with pytest.raises(HTTPException) as err:
            dataset(name)
        assert err.value.status_code == 400

    def test_unknown_song_is_404(self, data_dir):
        with pytest.raises(HTTPException) as err:
            dataset("missing")
        assert err.value.status_code == 404


class TestListDatasets:
    def test_skips_internal_and_broken_folders(self, data_dir, make_song):
        make_song("song", title="T", artist="A")
        (data_dir / "_uploads").mkdir()
        (data_dir / "broken").mkdir()
        names = [d["name"] for d in list_datasets()]
        assert names == ["song"]
