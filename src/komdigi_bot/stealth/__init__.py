"""Stealth browser sub-package.

Exposes :class:`SessionManager` (profile/UA rotation, human delays) and
:class:`StealthBrowser` (Playwright browser with anti-detection measures and
human-like interaction helpers) ported from *communiteyes-pro*.
"""

from komdigi_bot.stealth.browser import StealthBrowser
from komdigi_bot.stealth.session import SessionManager

__all__ = ["SessionManager", "StealthBrowser"]
