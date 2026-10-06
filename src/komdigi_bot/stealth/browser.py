"""Stealth Playwright browser with human-like interaction helpers.

Ported from *communiteyes-pro* ``scraper/stealth_browser.py`` and adapted for
the KOMDIGI captcha computer-use bot.  Key changes from the upstream version:

* Accepts a typed :class:`~komdigi_bot.config.StealthConfig` instead of a raw dict.
* Uses ``channel="chrome"`` (real Chrome channel) so Turnstile iframes render.
* ``human_click`` accepts either a CSS selector string *or* a pre-fetched
  bounding box dict so callers can pass solver-provided coordinates directly.
* ``human_type_into`` wraps ``pressSequentially`` for fields where
  ``keyboard.type`` does not trigger all DOM events.
* Adds ``screenshot`` helper for evidence collection.
* Context manager support (``__enter__`` / ``__exit__``).
"""

from __future__ import annotations

import random
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    sync_playwright,
)

from komdigi_bot.config import StealthConfig
from komdigi_bot.stealth.session import SessionManager

# ---------------------------------------------------------------------------
# Anti-automation init-script (injected into every page in the context)
# ---------------------------------------------------------------------------

_STEALTH_INIT_SCRIPT = """\
// Hide webdriver flag
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
// Fake plugin array (≥ 1 entry prevents "no plugins" detection)
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const arr = [1, 2, 3, 4, 5];
        arr.item = (i) => arr[i];
        arr.refresh = () => {};
        arr.namedItem = (n) => null;
        return arr;
    }
});
// Language list consistent with id-ID + en-US profiles
Object.defineProperty(navigator, 'languages', {
    get: () => ['id-ID', 'id', 'en-US', 'en']
});
// Minimal chrome.runtime to satisfy Turnstile + reCAPTCHA checks
window.chrome = { runtime: {} };
"""


class StealthBrowser:
    """Human-like Playwright browser for captcha solving tasks.

    Usage (explicit)::

        sb = StealthBrowser(cfg)
        page = sb.start()
        sb.navigate_human("https://2captcha.com/demo/normal")
        sb.stop()

    Usage (context manager, recommended)::

        with StealthBrowser(cfg) as page:
            page.goto("https://2captcha.com/demo/normal")

    Args:
        config: Typed :class:`~komdigi_bot.config.StealthConfig` instance.
        storage_dir: Passed to :class:`~komdigi_bot.stealth.session.SessionManager`.
        seed: Optional RNG seed for deterministic unit tests.
        storage_state: Optional path to a Playwright storage-state JSON
            (authenticated cookies, localStorage).
    """

    def __init__(
        self,
        config: StealthConfig,
        storage_dir: str | Path = "data/sessions",
        seed: int | None = None,
        storage_state: str | Path | None = None,
    ) -> None:
        self._cfg: StealthConfig = config
        self._storage_state: Path | None = Path(storage_state) if storage_state else None
        self._rng: random.Random = random.Random(seed)
        self.session_mgr: SessionManager = SessionManager(storage_dir=storage_dir, seed=seed)

        self._playwright: Any = None  # playwright.sync_api.SyncPlaywright at runtime
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> Page:
        """Launch Chromium (Chrome channel) with stealth args and return the active page."""
        self._playwright = sync_playwright().start()

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            f"--window-size={self._cfg.viewport_width},{self._cfg.viewport_height}",
            "--host-resolver-rules="
            "MAP democaptcha.com 77.222.40.38, "
            "MAP *.democaptcha.com 77.222.40.38, "
            "MAP 2captcha.com 104.26.10.235, "
            "MAP *.2captcha.com 104.26.10.235, "
            "MAP solvecaptcha.com 172.67.182.49, "
            "MAP *.solvecaptcha.com 172.67.182.49",
        ]

        browser_kwargs: dict[str, Any] = {
            "headless": self._cfg.headless,
            "channel": "chrome",  # real Chrome binary — required for Turnstile iframe render
            "args": launch_args,
        }
        if self._cfg.proxy:
            browser_kwargs["proxy"] = {"server": self._cfg.proxy}

        self._browser = self._playwright.chromium.launch(**browser_kwargs)

        # Rotate to the next profile
        session = self.session_mgr.rotate()

        context_kwargs: dict[str, Any] = {
            "viewport": {
                "width": session["viewport"][0],
                "height": session["viewport"][1],
            },
            "user_agent": session["user_agent"],
            "locale": session["language"],
        }
        if self._storage_state and self._storage_state.exists():
            context_kwargs["storage_state"] = str(self._storage_state)

        assert self._browser is not None  # launched two lines above
        self._context = self._browser.new_context(**context_kwargs)
        # Inject anti-detection script for every new page in this context
        _ = self._context.add_init_script(_STEALTH_INIT_SCRIPT)

        self._page = self._context.new_page()
        self._human_delay(1.0, 2.5)  # initial "boot" pause
        return self._page

    def stop(self) -> None:
        """Gracefully close context, browser, and Playwright."""
        import contextlib

        if self._context:
            with contextlib.suppress(Exception):
                self._context.close()
        if self._browser:
            with contextlib.suppress(Exception):
                self._browser.close()
        if self._playwright:
            with contextlib.suppress(Exception):
                self._playwright.stop()

    # Context-manager protocol
    def __enter__(self) -> Page:
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Human-like interaction helpers
    # ------------------------------------------------------------------

    def _human_delay(self, min_sec: float = 0.5, max_sec: float = 3.0) -> None:
        """Sleep for a random human-like duration (seconds)."""
        delay = self._rng.uniform(min_sec, max_sec)
        time.sleep(delay)

    def human_scroll(self, times: int | None = None) -> None:
        """Gradually scroll the page down like a human reader.

        Randomly scrolls 300–800 px per step; 30 % chance of a short scroll-back
        (simulating "re-reading").
        """
        if self._page is None:
            return
        count = times if times is not None else self._cfg.scroll_pages
        for _ in range(count):
            scroll_y = self._rng.randint(300, 800)
            self._page.evaluate(f"window.scrollBy(0, {scroll_y})")
            self._human_delay(1.0, 2.5 * (1 + self._rng.random()))
            if self._rng.random() < 0.3:
                back = self._rng.randint(50, 150)
                self._page.evaluate(f"window.scrollBy(0, -{back})")
                self._human_delay(0.3, 1.0)

    def human_type(self, selector: str, text: str) -> None:
        """Click *selector* then type each character with variable 30–120 ms delay."""
        if self._page is None:
            return
        self._page.click(selector)
        self._human_delay(0.2, 0.8)
        for char in text:
            self._page.keyboard.type(char, delay=self._rng.randint(30, 120))
        self._human_delay(0.3, 1.0)

    def human_type_into(self, selector: str, text: str) -> None:
        """Focus *selector* then use ``pressSequentially`` to dispatch full key events.

        Preferred over :meth:`human_type` when the target field listens on
        ``keydown`` / ``keyup`` events (e.g. captcha answer inputs).
        """
        if self._page is None:
            return
        element = self._page.locator(selector).first
        element.click()
        self._human_delay(0.2, 0.6)
        element.press_sequentially(text, delay=self._rng.randint(30, 120))
        self._human_delay(0.3, 1.0)

    def human_click(self, selector_or_box: str | dict[str, float]) -> None:
        """Click with a realistic hover-first mouse movement.

        Args:
            selector_or_box: CSS selector string **or** a bounding-box dict
                ``{"x": float, "y": float, "width": float, "height": float}``
                as returned by ``page.locator(...).bounding_box()``.
        """
        if self._page is None:
            return

        if isinstance(selector_or_box, dict):
            box = selector_or_box
            x = box["x"] + self._rng.uniform(5, max(6.0, box["width"] - 5))
            y = box["y"] + self._rng.uniform(5, max(6.0, box["height"] - 5))
            self._page.mouse.move(x, y)
            self._human_delay(0.1, 0.4)
            self._page.mouse.click(x, y)
        else:
            import contextlib

            with contextlib.suppress(Exception):
                box = self._page.locator(selector_or_box).bounding_box()
                if box:
                    x = box["x"] + self._rng.uniform(5, max(6.0, box["width"] - 5))
                    y = box["y"] + self._rng.uniform(5, max(6.0, box["height"] - 5))
                    self._page.mouse.move(x, y)
                    self._human_delay(0.1, 0.4)
            self._page.click(selector_or_box)

        self._human_delay(0.3, 1.5)

    def human_drag(self, source_box: dict[str, float], delta_x: float, delta_y: float) -> None:
        """Drag from the centre of *source_box* by *(delta_x, delta_y)* pixels.

        Movement is split into short steps with micro-jitter to mimic a human
        drag gesture (used by rotate-slider solvers).
        """
        if self._page is None:
            return
        sx = source_box["x"] + source_box["width"] / 2
        sy = source_box["y"] + source_box["height"] / 2
        self._page.mouse.move(sx, sy)
        self._human_delay(0.1, 0.3)
        self._page.mouse.down()
        self._human_delay(0.05, 0.15)

        steps = max(10, int(abs(delta_x + delta_y) // 5))
        for i in range(1, steps + 1):
            progress = i / steps
            # Ease-in-out curve for natural acceleration
            t = progress * progress * (3 - 2 * progress)
            jx = self._rng.uniform(-1.5, 1.5)
            jy = self._rng.uniform(-1.5, 1.5)
            self._page.mouse.move(sx + delta_x * t + jx, sy + delta_y * t + jy)
            time.sleep(self._rng.uniform(0.01, 0.03))

        self._page.mouse.up()
        self._human_delay(0.2, 0.6)

    def navigate_human(self, url: str, timeout: int = 30_000) -> None:
        """Go to *url* with a "deciding" pause before and a "reading" pause after."""
        if self._page is None:
            return
        self._human_delay(0.5, 2.0)
        _ = self._page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        self._human_delay(1.0, 3.5)

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def screenshot(self, path: str | Path, full_page: bool = False) -> Path:
        """Save a screenshot to *path* (parent dirs created automatically).

        Returns the resolved :class:`~pathlib.Path`.
        """
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        if self._page is None:
            raise RuntimeError("Browser not started — call start() first")
        _ = self._page.screenshot(path=str(out), full_page=full_page)
        return out

    def get_page(self) -> Page:
        """Return the active :class:`~playwright.sync_api.Page` (raises if not started)."""
        if self._page is None:
            raise RuntimeError("Browser not started — call start() first")
        return self._page

    @contextmanager
    def new_tab(self) -> Generator[Page, None, None]:
        """Open a fresh tab in the same context, yield it, then close it."""
        if self._context is None:
            raise RuntimeError("Browser not started — call start() first")
        tab = self._context.new_page()
        try:
            yield tab
        finally:
            tab.close()
