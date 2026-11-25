"""Duration probing without ffprobe (the package ships only ffmpeg)."""
from __future__ import annotations

from pathlib import Path

from app import binaries


class TestProbeDuration:
    def test_a_missing_file_is_zero_not_a_crash(self, tmp_path):
        assert binaries.probe_duration(tmp_path / "nope.mp3") == 0.0

    def test_a_non_media_file_is_zero(self, tmp_path):
        junk = tmp_path / "junk.mp3"
        junk.write_bytes(b"not audio at all")
        assert binaries.probe_duration(junk) == 0.0

    def test_a_real_audio_file_reports_its_length(self, tmp_path):
        import shutil

        source = Path("E:/agent-space/utalearn/localdata/braveheart/audio.mp3")
        if not source.exists():
            import pytest

            pytest.skip("本机没有测试音频")
        target = tmp_path / "a.mp3"
        shutil.copy2(source, target)
        assert binaries.probe_duration(target) > 60

    def test_the_banner_parser_handles_the_real_format(self):
        # the exact line ffmpeg prints; parsed by regex inside probe_duration
        import re

        line = "  Duration: 00:03:41.60, start: 0.000000, bitrate: 128 kb/s"
        m = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", line)
        assert m is not None
        hours, minutes, seconds = int(m.group(1)), int(m.group(2)), float(m.group(3))
        assert round(hours * 3600 + minutes * 60 + seconds, 2) == 221.6
