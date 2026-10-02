"""Triage sub-package — captcha family detection and engine routing."""

from komdigi_bot.triage.detector import CaptchaDetector, DetectionResult
from komdigi_bot.triage.router import CaptchaRouter, RoutingResult

__all__ = ["CaptchaDetector", "CaptchaRouter", "DetectionResult", "RoutingResult"]
