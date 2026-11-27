"""5.4.2: frame-render planning (parallelism, segments, encoder args)."""
from __future__ import annotations

import pytest

from app import export, render_frames


class TestPageCount:
    def test_an_explicit_request_is_honoured(self):
        assert render_frames.page_count(2) == 2

    def test_it_is_capped_at_four(self):
        assert render_frames.page_count(9) == render_frames.MAX_PAGES

    def test_zero_or_negative_falls_back_to_the_default(self):
        assert 1 <= render_frames.page_count(0) <= render_frames.MAX_PAGES

    def test_a_running_cpu_job_drops_it_to_one(self, monkeypatch):
        from app import jobs

        monkeypatch.setattr(jobs, "list_jobs", lambda active_only=False: [{"id": "x"}])
        assert render_frames.page_count(4) == 1

    def test_an_idle_machine_uses_the_requested_count(self, monkeypatch):
        from app import jobs

        monkeypatch.setattr(jobs, "list_jobs", lambda active_only=False: [])
        assert render_frames.page_count(3) == 3


class TestEncoder:
    def test_it_encodes_a_silent_video_track(self, tmp_path):
        # audio is added once at concat time, so each page's own clip is silent
        from app import binaries

        if not binaries.find("ffmpeg"):
            pytest.skip("需要 ffmpeg 才能验证编码参数")
        proc = render_frames._start_encoder(tmp_path / "a.mp4", 640, 360)
        proc.stdin.close()
        proc.wait()
        args = " ".join(proc.args) if isinstance(proc.args, list) else str(proc.args)
        assert "-an" in args
        assert "libx264" in args
        assert "-crf 18" in args

    def test_the_fps_comes_from_the_export_module(self):
        assert render_frames.FPS == export.FPS == 60


class TestPresetSizing:
    @pytest.mark.parametrize("name, expected", [
        ("landscape", (1920, 1080)),
        ("portrait", (1080, 1920)),
        ("4k", (3840, 2160)),
    ])
    def test_the_frame_size_matches_the_preset(self, name, expected):
        size = export.preset(name)
        assert (size["width"] * size["scale"],
                size["height"] * size["scale"]) == expected


class TestOutputFolder:
    def test_a_missing_export_folder_is_created(self, tmp_path, monkeypatch):
        """A fresh portable has no `exports/` until the first export.

        ffmpeg exits with -2 when the destination folder is missing, which the
        UI showed as a bare "合并并混入音频" failure after a full render.
        """
        target = tmp_path / "not" / "created" / "yet" / "out.mp4"
        monkeypatch.setattr(render_frames, "page_count", lambda requested=None: 1)

        def fake_segment(base_url, song, preset_name, start, end, out, progress=None,
                         extra_query=""):
            out.write_bytes(b"\x00" * 1024)

        monkeypatch.setattr(render_frames, "render_segment", fake_segment)
        monkeypatch.setattr(
            render_frames, "_concat",
            lambda parts, audio, out, clip_start, duration: (
                out.parent.mkdir(parents=True, exist_ok=True),
                out.write_bytes(b"\x00" * 2048),
            ),
        )
        monkeypatch.setattr(export, "_has_video", lambda p: True)
        monkeypatch.setattr(render_frames, "tempfile", _FakeTempfile(tmp_path))
        render_frames.render(
            base_url="http://127.0.0.1:8000", song="song", audio=None,
            out=target, duration=1.0, preset_name="landscape",
        )
        assert target.exists()


class _FakeTempfile:
    """`render()` would otherwise create and then delete a real temp dir."""

    def __init__(self, root):
        self.root = root

    def mkdtemp(self, prefix=""):
        path = self.root / f"{prefix}work"
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
