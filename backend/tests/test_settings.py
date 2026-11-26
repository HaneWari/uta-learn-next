"""Settings store + the proxy resolver that reads it."""
from __future__ import annotations

import json

import pytest

from app import settings


@pytest.fixture(autouse=True)
def temp_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")
    yield


class TestDefaults:
    def test_defaults_are_returned_with_no_file(self):
        data = settings.load()
        assert data["telemetry"] is True
        assert data["proxy_mode"] == "auto"
        assert data["default_layers"]["cards"] is True

    def test_a_corrupt_file_falls_back_to_defaults(self):
        settings.SETTINGS_FILE.write_text("{{{", encoding="utf-8")
        assert settings.load()["telemetry"] is True

    def test_a_non_object_file_falls_back_to_defaults(self):
        settings.SETTINGS_FILE.write_text("[1, 2]", encoding="utf-8")
        assert settings.load()["theme"] == "system"


class TestSave:
    def test_patch_is_merged_not_replaced(self):
        settings.save({"theme": "dark"})
        settings.save({"telemetry": False})
        data = settings.load()
        assert data["theme"] == "dark"
        assert data["telemetry"] is False

    def test_nested_layers_merge(self):
        settings.save({"default_layers": {"romaji": False}})
        layers = settings.load()["default_layers"]
        assert layers["romaji"] is False
        assert layers["furigana"] is True

    def test_unknown_keys_survive_a_round_trip(self):
        settings.save({"from_a_newer_build": {"x": 1}})
        assert settings.load()["from_a_newer_build"] == {"x": 1}

    def test_saved_file_is_json_without_ascii_escapes(self):
        settings.save({"proxy_url": "http://127.0.0.1:7890"})
        raw = settings.SETTINGS_FILE.read_text(encoding="utf-8")
        assert json.loads(raw)["proxy_url"] == "http://127.0.0.1:7890"

    def test_reset_restores_defaults(self):
        settings.save({"theme": "dark"})
        assert settings.reset()["theme"] == "system"
        assert not settings.SETTINGS_FILE.exists()

    def test_display_scale_defaults_exist(self):
        data = settings.load()
        assert data["ui_font"] == "m"
        assert data["page_zoom"] == 1.0


class TestProxyResolver:
    def test_off_mode_never_returns_a_proxy(self, monkeypatch):
        from app import sources

        settings.save({"proxy_mode": "off"})
        monkeypatch.setattr(sources, "getproxies",
                            lambda: {"https": "http://127.0.0.1:1111"})
        assert sources.resolve_proxy() is None

    def test_manual_mode_uses_the_configured_url(self):
        from app import sources

        settings.save({"proxy_mode": "manual",
                       "proxy_url": "http://127.0.0.1:7891"})
        assert sources.resolve_proxy() == "http://127.0.0.1:7891"

    def test_manual_mode_with_an_empty_url_is_direct(self):
        from app import sources

        settings.save({"proxy_mode": "manual", "proxy_url": "  "})
        assert sources.resolve_proxy() is None

    def test_system_mode_only_trusts_the_os(self, monkeypatch):
        from app import sources

        settings.save({"proxy_mode": "system"})
        monkeypatch.setattr(sources, "getproxies", lambda: {})
        monkeypatch.setattr(sources, "_probe_local_proxy",
                            lambda: pytest.fail("system 模式不该扫本地端口"))
        assert sources.resolve_proxy() is None

    def test_auto_mode_prefers_the_os_setting(self, monkeypatch):
        from app import sources

        settings.save({"proxy_mode": "auto"})
        monkeypatch.setattr(sources, "getproxies",
                            lambda: {"https": "http://10.0.0.1:3128"})
        assert sources.resolve_proxy() == "http://10.0.0.1:3128"

    def test_auto_mode_falls_back_to_a_local_port(self, monkeypatch):
        from app import sources

        settings.save({"proxy_mode": "auto"})
        monkeypatch.setattr(sources, "getproxies", lambda: {})
        monkeypatch.setattr(sources, "_probe_local_proxy",
                            lambda: "http://127.0.0.1:7890")
        assert sources.resolve_proxy() == "http://127.0.0.1:7890"

    def test_the_answer_is_not_cached(self, monkeypatch):
        from app import sources

        settings.save({"proxy_mode": "manual", "proxy_url": "http://a:1"})
        assert sources.resolve_proxy() == "http://a:1"
        settings.save({"proxy_url": "http://b:2"})
        assert sources.resolve_proxy() == "http://b:2"
