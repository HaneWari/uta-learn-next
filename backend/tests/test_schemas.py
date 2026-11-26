"""5.6.1: request models validate, document and stay forward-compatible."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import main
from app import schemas


class TestModels:
    def test_search_defaults_are_usable(self):
        req = schemas.SearchRequest(query="夜に駆ける")
        assert req.sources is None

    def test_unknown_fields_survive(self):
        """A rollback must not break on a field the newer front-end sends."""
        req = schemas.SearchRequest(query="x", from_a_future_version=1)
        assert req.model_extra == {"from_a_future_version": 1}

    def test_a_wrong_type_is_rejected(self):
        with pytest.raises(ValidationError):
            schemas.ExportRequest(clip_start="not a number")

    def test_export_defaults_to_the_whole_song(self):
        req = schemas.ExportRequest(song="a")
        assert req.clip_start is None and req.clip_end is None
        assert req.hide_cards is False

    def test_a_lyrics_only_build_needs_no_extra_keys(self):
        assert schemas.BuildTextRequest(upload_id="x", lyrics="a\nb").translate is False


class TestDocumented:
    @pytest.fixture
    def openapi(self):
        client = TestClient(main.app, base_url="http://127.0.0.1:8000")
        return client.get("/openapi.json").json()

    def test_the_search_body_is_described(self, openapi):
        body = openapi["paths"]["/api/search"]["post"]["requestBody"]
        ref = body["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/SearchRequest")

    def test_the_export_body_is_described(self, openapi):
        body = openapi["paths"]["/api/export"]["post"]["requestBody"]
        ref = body["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/ExportRequest")

    def test_settings_patch_is_described(self, openapi):
        body = openapi["paths"]["/api/settings"]["patch"]["requestBody"]
        ref = body["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/SettingsPatch")
