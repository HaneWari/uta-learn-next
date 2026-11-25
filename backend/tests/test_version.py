"""The version must live in one place and agree everywhere it is mirrored."""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

from app.version import APP_NAME, APP_VERSION

ROOT = Path(__file__).resolve().parents[2]


def test_version_is_semver():
    parts = APP_VERSION.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)
    assert APP_VERSION.startswith("2.")


def test_pyproject_does_not_pin_its_own_version():
    data = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in data["project"]
    assert data["project"]["dynamic"] == ["version"]
    assert data["tool"]["setuptools"]["dynamic"]["version"]["attr"] == \
        "app.version.APP_VERSION"


def test_frontend_manifest_matches():
    pkg = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert pkg["version"] == APP_VERSION


def test_name():
    assert APP_NAME == "UtaLearn Next"
