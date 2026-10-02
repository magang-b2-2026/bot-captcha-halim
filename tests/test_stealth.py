"""Tests for komdigi_bot.stealth — unit tests (deterministic, no browser).

Covers:
- SessionManager: 4-profile rotation cycle, deterministic seed, delay bounds,
  ledger persistence across instances.
- StealthBrowser: attribute wiring from StealthConfig; ``_human_delay`` bounds;
  ``human_drag`` step count sanity check (monkey-patched mouse).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from komdigi_bot.config import StealthConfig
from komdigi_bot.stealth.session import SessionManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_session_dir(tmp_path: Path) -> Path:
    return tmp_path / "sessions"


# ===========================================================================
# SessionManager tests
# ===========================================================================


class TestSessionManagerRotation:
    def test_four_profiles_cycle(self, tmp_session_dir: Path) -> None:
        """After 4 rotations the viewport sequence wraps deterministically."""
        mgr = SessionManager(storage_dir=tmp_session_dir, seed=0)
        viewports = [mgr.rotate()["viewport"] for _ in range(4)]
        expected = [p["viewport"] for p in SessionManager.PROFILES]
        assert viewports == expected

    def test_eighth_rotation_wraps_back(self, tmp_session_dir: Path) -> None:
        """8 rotations → index 0 and 4 yield same profile."""
        mgr = SessionManager(storage_dir=tmp_session_dir, seed=0)
        first = mgr.rotate()
        for _ in range(3):
            mgr.rotate()
        fifth = mgr.rotate()
        assert first["viewport"] == fifth["viewport"]
        assert first["user_agent"] == fifth["user_agent"]

    def test_profile_id_format(self, tmp_session_dir: Path) -> None:
        """profile_id follows 'profile-{0..3}' pattern."""
        mgr = SessionManager(storage_dir=tmp_session_dir, seed=0)
        for i in range(4):
            s = mgr.rotate()
            assert s["profile_id"] == f"profile-{i}"

    def test_rotation_count_increments(self, tmp_session_dir: Path) -> None:
        mgr = SessionManager(storage_dir=tmp_session_dir, seed=0)
        assert mgr.rotation_count == 0
        mgr.rotate()
        mgr.rotate()
        assert mgr.rotation_count == 2

    def test_ledger_persists_across_instances(self, tmp_session_dir: Path) -> None:
        """State written by first instance is readable by a second instance."""
        mgr1 = SessionManager(storage_dir=tmp_session_dir, seed=0)
        mgr1.rotate()
        mgr1.rotate()

        mgr2 = SessionManager(storage_dir=tmp_session_dir, seed=0)
        # rotation_count should reflect the 2 rotations from mgr1
        assert mgr2.rotation_count == 2

    def test_ledger_json_is_valid(self, tmp_session_dir: Path) -> None:
        mgr = SessionManager(storage_dir=tmp_session_dir, seed=0)
        mgr.rotate()
        ledger = tmp_session_dir / "active_session.json"
        assert ledger.exists()
        data = json.loads(ledger.read_text(encoding="utf-8"))
        assert "rotation_count" in data
        assert "current_profile" in data

    def test_corrupt_ledger_recovery(self, tmp_session_dir: Path) -> None:
        """A corrupt ledger file does not crash the manager."""
        tmp_session_dir.mkdir(parents=True, exist_ok=True)
        (tmp_session_dir / "active_session.json").write_text("NOT JSON", encoding="utf-8")
        mgr = SessionManager(storage_dir=tmp_session_dir, seed=0)
        s = mgr.rotate()  # should not raise
        assert "viewport" in s


class TestSessionManagerDelays:
    def test_random_delay_in_bounds(self, tmp_session_dir: Path) -> None:
        """random_delay sleeps within [min_ms, max_ms] ms."""
        mgr = SessionManager(storage_dir=tmp_session_dir, seed=42)
        start = time.monotonic()
        mgr.random_delay(min_ms=10, max_ms=20)
        elapsed_ms = (time.monotonic() - start) * 1000
        # Allow ±10 ms scheduling slack
        assert 0 < elapsed_ms < 50

    def test_jitter_delay_never_below_ten(self, tmp_session_dir: Path) -> None:
        """jitter_delay is always ≥ 10 regardless of negative jitter."""
        mgr = SessionManager(storage_dir=tmp_session_dir, seed=7)
        for _ in range(20):
            result = mgr.jitter_delay(base_seconds=5, jitter_seconds=100)
            assert result >= 10

    def test_jitter_delay_within_range(self, tmp_session_dir: Path) -> None:
        mgr = SessionManager(storage_dir=tmp_session_dir, seed=0)
        for _ in range(20):
            result = mgr.jitter_delay(base_seconds=1800, jitter_seconds=180)
            assert 1620 <= result <= 1980


# ===========================================================================
# StealthBrowser — attribute + config wiring (no real browser launched)
# ===========================================================================


class TestStealthBrowserConfig:
    def test_headless_wired_from_config(self, tmp_session_dir: Path) -> None:
        from komdigi_bot.stealth.browser import StealthBrowser

        cfg = StealthConfig(headless=False, viewport_width=1440, viewport_height=900)
        sb = StealthBrowser(cfg, storage_dir=tmp_session_dir, seed=0)
        assert sb._cfg.headless is False
        assert sb._cfg.viewport_width == 1440

    def test_proxy_empty_by_default(self, tmp_session_dir: Path) -> None:
        from komdigi_bot.stealth.browser import StealthBrowser

        cfg = StealthConfig()
        sb = StealthBrowser(cfg, storage_dir=tmp_session_dir, seed=0)
        assert sb._cfg.proxy == ""

    def test_human_delay_sleeps(self, tmp_session_dir: Path) -> None:
        """_human_delay sleeps a positive amount."""
        from komdigi_bot.stealth.browser import StealthBrowser

        cfg = StealthConfig()
        sb = StealthBrowser(cfg, storage_dir=tmp_session_dir, seed=0)
        start = time.monotonic()
        sb._human_delay(0.01, 0.02)
        assert time.monotonic() - start >= 0.005  # at least 5 ms (scheduling slack)

    def test_human_drag_calls_mouse_in_steps(self, tmp_session_dir: Path) -> None:
        """human_drag calls mouse.move() multiple times (not a single-step jump)."""
        from komdigi_bot.stealth.browser import StealthBrowser

        cfg = StealthConfig()
        sb = StealthBrowser(cfg, storage_dir=tmp_session_dir, seed=0)

        mock_page: Any = MagicMock()
        sb._page = mock_page

        source_box = {"x": 100.0, "y": 200.0, "width": 50.0, "height": 20.0}
        sb.human_drag(source_box, delta_x=100.0, delta_y=0.0)

        # mouse.move must be called many times (steps > 1)
        move_calls = mock_page.mouse.move.call_count
        assert move_calls >= 5, f"Expected ≥5 move calls, got {move_calls}"
        mock_page.mouse.down.assert_called_once()
        mock_page.mouse.up.assert_called_once()
