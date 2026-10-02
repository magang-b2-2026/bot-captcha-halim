"""DOM-signature captcha family detector.

Detects which captcha family is present on a page by inspecting the page
HTML for known script URLs, iframe src patterns, and DOM class/attribute
markers.

Families detected (in priority order):
    turnstile      — Cloudflare Turnstile
    recaptcha      — Google reCAPTCHA v2 checkbox / enterprise / v3
    hcaptcha       — hCaptcha
    arkose         — Arkose Labs / FunCaptcha
    geetest        — GeeTest v3 / v4
    image          — Image-selection CAPTCHA (click on objects in image)
    rotate         — Rotating image/slider CAPTCHA
    click          — Click-on-coordinates CAPTCHA
    text           — Text / math CAPTCHA (answer in plain text input)
    none           — No captcha detected

Each detection returns a :class:`DetectionResult` with the matched family,
a confidence score (0.0–1.0), and the list of signatures that fired.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import ClassVar

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class DetectionResult:
    """Outcome of a captcha-family detection pass."""

    family: str  # one of FAMILIES or "none"
    confidence: float  # 0.0 – 1.0
    matched_signatures: list[str] = field(default_factory=list)

    @property
    def detected(self) -> bool:
        return self.family != "none"


# ---------------------------------------------------------------------------
# Signature rules
# ---------------------------------------------------------------------------
# Each rule is a tuple: (compiled regex, weight)
# Weights are summed; confidence = min(1.0, total_weight / CONFIDENCE_SCALE)
# ---------------------------------------------------------------------------

_FAMILIES_ORDERED = [
    "turnstile",
    "recaptcha",
    "hcaptcha",
    "arkose",
    "geetest",
    "text",    # text before image: solvecaptcha.com text-captcha shares image DOM (ts-box/ts-form)
    "image",
    "rotate",
    "click",
]

# Scale factor — a family needs rules totalling ≥ 1.0 to reach full confidence
_CONFIDENCE_SCALE = 1.0

_RULES: dict[str, list[tuple[re.Pattern[str], float]]] = {
    "turnstile": [
        (re.compile(r"challenges\.cloudflare\.com/turnstile", re.IGNORECASE), 0.7),
        (re.compile(r"cf-turnstile", re.IGNORECASE), 0.5),
        (re.compile(r"window\.turnstile", re.IGNORECASE), 0.6),
        (re.compile(r"data-sitekey.*0x", re.IGNORECASE), 0.3),
    ],
    "recaptcha": [
        (re.compile(r"google\.com/recaptcha/api", re.IGNORECASE), 0.7),
        (re.compile(r"grecaptcha", re.IGNORECASE), 0.5),
        (re.compile(r"g-recaptcha", re.IGNORECASE), 0.5),
        (re.compile(r"recaptcha/api2/anchor", re.IGNORECASE), 0.8),
        (re.compile(r"recaptcha/enterprise", re.IGNORECASE), 0.6),
    ],
    "hcaptcha": [
        (re.compile(r"hcaptcha\.com/1/api", re.IGNORECASE), 0.8),
        (re.compile(r"h-captcha", re.IGNORECASE), 0.6),
        (re.compile(r"data-hcaptcha-sitekey", re.IGNORECASE), 0.7),
    ],
    "arkose": [
        (re.compile(r"arkoselabs\.com", re.IGNORECASE), 0.8),
        (re.compile(r"funcaptcha", re.IGNORECASE), 0.7),
        (re.compile(r"fc-token", re.IGNORECASE), 0.5),
    ],
    "geetest": [
        (re.compile(r"geetest\.com", re.IGNORECASE), 0.7),
        (re.compile(r"initGeetest", re.IGNORECASE), 0.7),
        (re.compile(r"gt\.js", re.IGNORECASE), 0.4),
        (re.compile(r"GeetestCaptcha", re.IGNORECASE), 0.6),
    ],
    "image": [
        # 2captcha demo
        (re.compile(r'alt=["\']normal captcha', re.IGNORECASE), 0.8),
        (re.compile(r"captcha.*image|image.*captcha", re.IGNORECASE), 0.4),
        (re.compile(r"Enter.*answer.*here|captchaCode|captcha_input", re.IGNORECASE), 0.3),
        # solvecaptcha.com image-captcha specific signatures
        (re.compile(r'id=["\']ts-box["\']', re.IGNORECASE), 0.6),
        (re.compile(r'id=["\']ts-form["\']', re.IGNORECASE), 0.5),
        (re.compile(r'id=["\']ts_submit["\']', re.IGNORECASE), 0.5),
        (re.compile(r'captcha\.jpg', re.IGNORECASE), 0.5),
        (re.compile(r'Image Captcha demo', re.IGNORECASE), 0.9),
        (re.compile(r'Enter text from the image', re.IGNORECASE), 0.9),
    ],
    "rotate": [
        (re.compile(r"rotatecaptcha|rotate.*captcha|captcha.*rotat", re.IGNORECASE), 0.8),
        (re.compile(r"rotate.*slider|slider.*angle", re.IGNORECASE), 0.5),
    ],
    "click": [
        (re.compile(r"clickcaptcha|click.*captcha|captcha.*click", re.IGNORECASE), 0.8),
        (re.compile(r"click.*coordinate|canvas.*captcha", re.IGNORECASE), 0.4),
    ],
    "text": [
        # Strong: solvecaptcha.com text-captcha discriminating signatures
        (re.compile(r'Text captcha demo', re.IGNORECASE), 1.5),    # page heading (unique to text page)
        (re.compile(r'/demo/text-captcha', re.IGNORECASE), 1.0),   # URL in page source/meta
        (re.compile(r'<title[^>]*>.*text.captcha.*</title>', re.IGNORECASE), 0.9),
        # 2captcha demo text: must have .text-captcha class OR explicit text-question
        (re.compile(r'class=["\'][^"\']*\btext-captcha\b', re.IGNORECASE), 0.8),
        (re.compile(r"(what|which|solve|answer|calculate).*\?", re.IGNORECASE), 0.3),
        # Generic text markers — only strong when paired with other signals
        (re.compile(r"text.*captcha|captcha.*text", re.IGNORECASE), 0.3),
        (re.compile(r'id=["\']answer["\']', re.IGNORECASE), 0.4),
    ],
}

_MIN_CONFIDENCE = 0.25  # below this → treat as no-match for that family


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class CaptchaDetector:
    """Detect captcha family from page HTML/text content.

    Args:
        min_confidence: Minimum score for a family to be reported as detected.
            Families below this score are ignored.
    """

    FAMILIES: ClassVar[list[str]] = _FAMILIES_ORDERED + ["none"]

    def __init__(self, min_confidence: float = _MIN_CONFIDENCE) -> None:
        self._min_confidence = min_confidence

    def detect(self, html: str) -> DetectionResult:
        """Scan *html* for captcha signatures.

        Returns the highest-confidence :class:`DetectionResult`.  If no family
        reaches ``min_confidence``, returns ``DetectionResult(family="none", confidence=0.0)``.

        Families are evaluated in priority order (turnstile first) so that
        a Cloudflare page embedding a reCAPTCHA fallback is classified as
        ``turnstile``.
        """
        best = DetectionResult(family="none", confidence=0.0)

        for family in _FAMILIES_ORDERED:
            rules = _RULES.get(family, [])
            total_weight = 0.0
            matched: list[str] = []

            for pattern, weight in rules:
                if pattern.search(html):
                    total_weight += weight
                    matched.append(pattern.pattern)

            confidence = min(1.0, total_weight / _CONFIDENCE_SCALE)
            if confidence >= self._min_confidence and confidence > best.confidence:
                best = DetectionResult(
                    family=family,
                    confidence=confidence,
                    matched_signatures=matched,
                )

        return best

    def detect_all(self, html: str) -> list[DetectionResult]:
        """Return all detected families above ``min_confidence``, sorted by confidence desc."""
        results: list[DetectionResult] = []
        for family in _FAMILIES_ORDERED:
            rules = _RULES.get(family, [])
            total_weight = 0.0
            matched: list[str] = []
            for pattern, weight in rules:
                if pattern.search(html):
                    total_weight += weight
                    matched.append(pattern.pattern)
            confidence = min(1.0, total_weight / _CONFIDENCE_SCALE)
            if confidence >= self._min_confidence:
                results.append(
                    DetectionResult(
                        family=family,
                        confidence=confidence,
                        matched_signatures=matched,
                    )
                )
        results.sort(key=lambda r: r.confidence, reverse=True)
        return results
