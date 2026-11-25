"""Request/response shapes (5.6.1).

Every route used to take a bare `payload: dict`, which meant a typo in a field
name silently did nothing and the OpenAPI document described nothing useful.
These models fix both: FastAPI now validates and documents the traffic, and
`extra="allow"` keeps a newer front-end able to send fields an older backend
does not know yet (a patch update installed backwards by a rollback).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Lenient(BaseModel):
    """Base: unknown fields are preserved instead of rejected."""

    model_config = ConfigDict(extra="allow")


class SearchRequest(Lenient):
    query: str = ""
    sources: list[str] | None = None
    duration: float = 0.0
    sort: str = "duration"


class BuildRequest(Lenient):
    song: dict[str, Any] = Field(default_factory=dict)
    upload_id: str | None = None
    title: str = ""
    artist: str = ""
    lyric_start: str = ""
    audio_start: str = ""


class BuildTextRequest(Lenient):
    upload_id: str = ""
    lyrics: str = ""
    title: str = ""
    artist: str = ""
    translate: bool = False


class BuildLocalRequest(Lenient):
    lyrics_token: str = ""
    upload_id: str = ""
    title: str = ""
    artist: str = ""


class ExportRequest(Lenient):
    song: str = ""
    preset: str | None = None
    clip_start: float | None = None
    clip_end: float | None = None
    hide_cards: bool = False


class RevealRequest(Lenient):
    file: str | None = None


class ProxyTestRequest(Lenient):
    proxy_url: str = ""


class SettingsPatch(Lenient):
    """Validated in the route against `settings.DEFAULTS`, not hard-coded here:
    the allowed keys live in one place and a new setting is one line there."""

    model_config = ConfigDict(extra="allow")


class VocabItem(Lenient):
    song: str = ""
    segment_id: int | None = None
    text: str = ""


class UpdateApplyRequest(Lenient):
    manifest: dict[str, Any] | None = None


class JobResult(Lenient):
    id: str
    kind: str
    resource: str = "cpu"
    status: str
    progress: float = 0.0
    message: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None


class VersionInfo(Lenient):
    name: str
    version: str
    schema_version: int
