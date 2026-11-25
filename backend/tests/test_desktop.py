"""Desktop shell helpers: port choice and readiness wait (no GUI, no server)."""
from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import desktop  # noqa: E402


class TestFreePort:
    def test_returns_the_first_free_port(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            taken = probe.getsockname()[1]
            # ask for a one-port range that is already bound
            with pytest.raises(SystemExit):
                desktop.free_port(taken, taken)

    def test_a_free_range_yields_a_bindable_port(self):
        port = desktop.free_port(18000, 18010)
        assert 18000 <= port <= 18010

    def test_an_inverted_range_is_fatal(self):
        with pytest.raises(SystemExit):
            desktop.free_port(18010, 18000)


class TestWaitReady:
    def test_times_out_against_a_closed_port(self):
        # nothing listens on an unlikely port; the helper must give up, not hang
        assert desktop.wait_ready("http://127.0.0.1:9", timeout=0.4) is False
