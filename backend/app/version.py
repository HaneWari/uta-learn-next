"""Single source of truth for the app version.
`pyproject.toml` reads it through setuptools' dynamic-version hook, the portable
build imports it, and `/api/version` serves it to the UI — so a release bump
happens in exactly one place.
"""
APP_NAME = "UtaLearn Next"
APP_VERSION = "2.0.0"
