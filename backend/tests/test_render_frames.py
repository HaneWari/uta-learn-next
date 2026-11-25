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
