"""Session profile rotation and human-like delay helpers.

Ported from *communiteyes-pro* ``scraper/session_manager.py`` and extended
with deterministic seed support (for unit testing) and integration with the
KOMDIGI :class:`~komdigi_bot.config.StealthConfig`.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any, ClassVar


class SessionManager:
    """Manage browser session profiles for stealth automation.

    Rotates through 4 distinct viewport / platform / language / UA
    combinations so each attempt appears to be a different browser/device.
    A lightweight JSON ledger in *storage_dir* persists rotation state so the
    index survives process restarts.

    Args:
        storage_dir: Directory where ``active_session.json`` is written.
            Defaults to ``data/sessions`` (relative to CWD).  Created if
            missing.
        seed: Optional RNG seed — pass an integer for deterministic tests.
    """

    # 4 profiles as in communiteyes-pro, covering Win/Mac/Linux and id/en
    PROFILES: ClassVar[list[dict[str, Any]]] = [
        {"viewport": (1366, 768), "platform": "Win32", "language": "id-ID"},
        {"viewport": (1440, 900), "platform": "MacIntel", "language": "en-US"},
        {"viewport": (1280, 800), "platform": "Win32", "language": "id-ID"},
        {"viewport": (1920, 1080), "platform": "Linux x86_64", "language": "en-US"},
    ]

    USER_AGENTS: ClassVar[list[str]] = [
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
    ]

    def __init__(
        self,
        storage_dir: str | Path = "data/sessions",
        seed: int | None = None,
    ) -> None:
        self._rng: random.Random = random.Random(seed)
        self.storage_dir: Path = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._current_index: int = 0
        self._session_data: dict[str, Any] = {}
        self._load_or_init()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_or_init(self) -> None:
        session_file = self.storage_dir / "active_session.json"
        if session_file.exists():
            try:
                with open(session_file, encoding="utf-8") as f:
                    self._session_data = json.load(f)
                    self._current_index = self._session_data.get("current_profile", {}).get(
                        "index", 0
                    )
            except (json.JSONDecodeError, OSError):
                self._session_data = {"rotation_count": 0}
        else:
            self._session_data = {"rotation_count": 0}

    def _save(self) -> None:
        session_file = self.storage_dir / "active_session.json"
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(self._session_data, f, indent=2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rotate(self) -> dict[str, Any]:
        """Advance to the next profile and return the resolved session dict.

        The returned dict contains::

            {
                "index": int,          # sequential rotation counter
                "viewport": (w, h),    # (width, height) tuple
                "platform": str,
                "language": str,
                "user_agent": str,
                "profile_id": str,     # "profile-{0..3}" for tagging
            }
        """
        profile = self.PROFILES[self._current_index % len(self.PROFILES)]
        ua = self.USER_AGENTS[self._current_index % len(self.USER_AGENTS)]
        profile_id = f"profile-{self._current_index % len(self.PROFILES)}"
        self._current_index += 1
        self._session_data["rotation_count"] = self._session_data.get("rotation_count", 0) + 1
        self._session_data["last_rotation"] = time.time()
        self._session_data["current_profile"] = {
            "index": self._current_index,
            "viewport": list(profile["viewport"]),  # JSON-serialisable
            "platform": profile["platform"],
            "language": profile["language"],
            "user_agent": ua,
            "profile_id": profile_id,
        }
        self._save()
        # Return with tuple for Playwright compat
        return {
            "index": self._current_index,
            "viewport": profile["viewport"],
            "platform": profile["platform"],
            "language": profile["language"],
            "user_agent": ua,
            "profile_id": profile_id,
        }

    def random_delay(self, min_ms: int = 500, max_ms: int = 3000) -> None:
        """Block the calling thread for a human-like random duration.

        Args:
            min_ms: Lower bound in milliseconds.
            max_ms: Upper bound in milliseconds.
        """
        delay = self._rng.uniform(min_ms, max_ms) / 1000.0
        time.sleep(delay)

    def jitter_delay(self, base_seconds: int, jitter_seconds: int) -> float:
        """Return a jittered interval (never below 10 s).

        Args:
            base_seconds: Central value.
            jitter_seconds: Maximum deviation above or below.

        Returns:
            Computed interval in seconds (≥ 10).
        """
        jitter = self._rng.randint(-jitter_seconds, jitter_seconds)
        return max(10, base_seconds + jitter)

    @property
    def rotation_count(self) -> int:
        """Total number of rotations since initialisation."""
        return int(self._session_data.get("rotation_count", 0))
