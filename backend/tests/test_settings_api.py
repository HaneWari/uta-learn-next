"""PATCH /api/settings: the route used to reject every write (bug #10)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main
from app import settings


@pytest.fixture(autouse=True)
def temp_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")


@pytest.fixture
def client():
    return TestClient(main.app, base_url="http://127.0.0.1:8000")


def test_a_patch_is_saved_and_survives_a_reread(client):
    r = client.patch("/api/settings", json={"theme": "dark", "reduce_motion": True})
    assert r.status_code == 200
    assert r.json()["theme"] == "dark"
    assert client.get("/api/settings").json()["theme"] == "dark"
    assert client.get("/api/settings").json()["reduce_motion"] is True


def test_nested_layers_patch_keeps_the_other_keys(client):
    client.patch("/api/settings", json={"default_layers": {"cards": False}})
    layers = client.get("/api/settings").json()["default_layers"]
    assert layers["cards"] is False
    assert layers["furigana"] is True


def test_an_unknown_key_is_refused(client):
    r = client.patch("/api/settings", json={"nope": 1})
    assert r.status_code == 400
    assert "nope" in r.json()["detail"]


def test_display_scale_values_are_validated(client):
    assert client.patch("/api/settings", json={"ui_font": "l"}).status_code == 200
    assert client.patch("/api/settings", json={"ui_font": "huge"}).status_code == 400
    assert client.patch("/api/settings", json={"page_zoom": 1.25}).status_code == 200
    assert client.patch("/api/settings", json={"page_zoom": 3}).status_code == 400
    assert client.patch("/api/settings", json={"page_zoom": 0.5}).status_code == 400


def test_play_style_and_karaoke_colour_are_validated(client):
    assert client.patch("/api/settings", json={"play_style": "karaoke"}).status_code == 200
    assert client.patch("/api/settings", json={"karaoke_color": "red"}).status_code == 200
    assert client.patch("/api/settings", json={"karaoke_color": "blue"}).status_code == 200
    assert client.patch("/api/settings", json={"play_style": "concert"}).status_code == 400
    assert client.patch("/api/settings", json={"karaoke_color": "pink"}).status_code == 400


def test_display_defaults_include_the_playback_style(client):
    data = client.get("/api/settings").json()
    assert data["play_style"] == "default"
    assert data["karaoke_color"] == "red"


def test_karaoke_style_options_are_validated(client):
    data = client.get("/api/settings").json()
    assert data["karaoke_scanline_enabled"] is True
    assert data["karaoke_scanline_width"] == 16
    assert data["karaoke_font"] == "gothic"

    assert (
        client.patch(
            "/api/settings",
            json={
                "karaoke_custom_colors": True,
                "karaoke_after_color": "#33AAFF",
                "karaoke_font": "mincho",
                "karaoke_stroke_width": 3,
                "karaoke_scanline_width": 24,
            },
        ).status_code
        == 200
    )
    saved = client.get("/api/settings").json()
    assert saved["karaoke_after_color"] == "#33AAFF"
    assert saved["karaoke_font"] == "mincho"

    assert (
        client.patch("/api/settings", json={"karaoke_after_color": "red"}).status_code
        == 400
    )
    assert (
        client.patch("/api/settings", json={"karaoke_font": "comic"}).status_code
        == 400
    )
    assert (
        client.patch("/api/settings", json={"karaoke_stroke_width": 12}).status_code
        == 400
    )
