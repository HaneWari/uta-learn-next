"""Diagnostic bundles and the anonymous heartbeat."""
from __future__ import annotations

import datetime as dt
import json
import zipfile

import pytest

from app import logs, settings, telemetry


@pytest.fixture(autouse=True)
def temp_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")
    yield


class TestScrub:
    def test_windows_user_path_is_masked(self):
        assert logs.scrub(r"C:\Users\alice\AppData\localdata") == \
            r"C:\Users\<user>\AppData\localdata"

    def test_unix_home_is_masked(self):
        assert logs.scrub("/home/bob/app") == "/home/<user>/app"

    def test_text_without_a_path_is_untouched(self):
        assert logs.scrub("歌词源不可用") == "歌词源不可用"


class TestBundle:
    def test_bundle_has_environment_and_log(self, tmp_path):
        dest = tmp_path / "diag.zip"
        logs.build_bundle(dest, {"extra.txt": "hello"})
        with zipfile.ZipFile(dest) as z:
            names = set(z.namelist())
            assert {"environment.json", "log.txt", "README.txt", "extra.txt"} <= names
            env = json.loads(z.read("environment.json"))
            assert env["version"]
            assert env["app"]

    def test_bundle_never_contains_the_install_id(self, tmp_path):
        settings.save({"install_id": "4f1c2a9e-7b3d-4e2a-9c61-0d8e5b7a3f10",
                       "telemetry_last_day": "2026-01-01"})
        dest = tmp_path / "diag.zip"
        logs.build_bundle(dest)
        with zipfile.ZipFile(dest) as z:
            body = z.read("environment.json").decode()
        assert "4f1c2a9e" not in body
        assert "2026-01-01" not in body

    def test_extra_text_is_scrubbed(self, tmp_path):
        dest = tmp_path / "diag.zip"
        logs.build_bundle(dest, {"note.txt": r"failed in C:\Users\carol\app"})
        with zipfile.ZipFile(dest) as z:
            note = z.read("note.txt").decode()
        assert "carol" not in note
        assert "<user>" in note


class TestTelemetry:
    def test_disabled_in_dev(self, monkeypatch):
        monkeypatch.setenv("UTALEARN_DEV", "1")
        assert telemetry.enabled() is False

    def test_disabled_by_env_var(self, monkeypatch):
        monkeypatch.delenv("UTALEARN_DEV", raising=False)
        monkeypatch.setenv("UTALEARN_TELEMETRY", "0")
        assert telemetry.enabled() is False

    def test_disabled_by_the_setting(self, monkeypatch):
        monkeypatch.delenv("UTALEARN_DEV", raising=False)
        monkeypatch.delenv("UTALEARN_TELEMETRY", raising=False)
        monkeypatch.delenv("CI", raising=False)
        settings.save({"telemetry": False})
        assert telemetry.enabled() is False

    def test_install_id_is_a_uuid_and_is_reused(self):
        first = telemetry.install_id()
        assert len(first) == 36 and first.count("-") == 4
        assert telemetry.install_id() == first

    def test_payload_has_exactly_three_fields(self):
        assert set(telemetry.payload()) == {"iid", "v", "os"}

    def test_os_bucket_is_whitelisted(self):
        assert telemetry.os_bucket() in ("win10", "win11", "other")

    def test_one_heartbeat_per_day(self, monkeypatch):
        monkeypatch.delenv("UTALEARN_DEV", raising=False)
        monkeypatch.delenv("UTALEARN_TELEMETRY", raising=False)
        monkeypatch.delenv("CI", raising=False)
        settings.save({"telemetry": True})
        sent = []

        class FakeResponse:
            status_code = 204

        class FakeClient:
            def __init__(self, **_kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def post(self, url, json=None):
                sent.append((url, json))
                return FakeResponse()

        monkeypatch.setattr(telemetry.httpx, "Client", FakeClient)
        day = dt.date(2026, 11, 25)
        assert telemetry.send(day) is True
        assert telemetry.send(day) is False
        assert len(sent) == 1
        assert sent[0][0] == telemetry.TELEMETRY_URL
        assert set(sent[0][1]) == {"iid", "v", "os"}

    def test_a_network_failure_is_silent(self, monkeypatch):
        monkeypatch.delenv("UTALEARN_DEV", raising=False)
        monkeypatch.delenv("UTALEARN_TELEMETRY", raising=False)
        monkeypatch.delenv("CI", raising=False)
        settings.save({"telemetry": True})

        class BoomClient:
            def __init__(self, **_kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def post(self, *_a, **_kw):
                raise telemetry.httpx.ConnectError("offline")

        monkeypatch.setattr(telemetry.httpx, "Client", BoomClient)
        assert telemetry.send(dt.date(2026, 11, 25)) is False
        # a failure does not mark the day as done, but also never raises
        assert settings.get("telemetry_last_day") == ""
