"""Captcha family router — Jev-backed routing + pre-gate.

Routes the output of :class:`~komdigi_bot.triage.detector.CaptchaDetector`
through Jev SystemOne for final validation and decision-making:

1. **Pre-gate (noul):** "Is there no captcha on this page?" — if True with
   high confidence, short-circuit to ``none`` without spending tokens on a
   choice call.
2. **Route (choice):** Given the detected DOM family + confidence, ask Jev to
   confirm the engine that should be dispatched.

Both Jev calls are optional — if ``jev_client`` is ``None`` (e.g. key not
configured), the router falls back to returning the raw detector result.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from komdigi_bot.decision.jev import (
    JevAnswerNoul,
    JevAuthError,
    JevClient,
    JevResponseError,
    JevServerError,
)
from komdigi_bot.triage.detector import CaptchaDetector, DetectionResult

logger = logging.getLogger(__name__)

# Threshold above which a Jev noul "no captcha" answer short-circuits routing
_NO_CAPTCHA_NOUL_THRESHOLD = 0.85

# Engines available to the Jev choice question
_ENGINE_CRITERIA: dict[str, str] = {
    "text_reasoning": "Plain text or math question answered by reasoning",
    "image_ocr": "Image/photo captcha requiring text transcription",
    "click_coords": "Click on specific objects/coordinates within an image",
    "rotate_slide": "Rotate or slide a puzzle piece to a target position",
    "checkbox_grid": "Multi-image grid selection (e.g. reCAPTCHA grid)",
    "api_fallback": "Complex or enterprise captcha best solved via external API",
    "none": "No captcha is present on this page",
}


@dataclass
class RoutingResult:
    """Final routing decision."""

    family: str  # detected captcha family
    engine: str  # engine key (matches _ENGINE_CRITERIA keys)
    confidence: float  # detector confidence
    jev_confirmed: bool  # True if Jev confirmed the routing
    pre_gated_none: bool  # True if Jev noul short-circuited (no captcha)


class CaptchaRouter:
    """Route page HTML to the appropriate solver engine.

    Args:
        detector: :class:`~komdigi_bot.triage.detector.CaptchaDetector` instance.
        jev_client: Optional :class:`~komdigi_bot.decision.jev.JevClient`.
            When ``None``, routing uses detector output directly.
        heavy_families: Families to route to ``api_fallback`` engine.
    """

    # Map detector family → default engine (used when Jev is unavailable)
    _FAMILY_ENGINE_MAP: ClassVar[dict[str, str]] = {
        "turnstile": "api_fallback",  # requires token injection
        "recaptcha": "checkbox_grid",
        "hcaptcha": "checkbox_grid",
        "arkose": "api_fallback",
        "geetest": "api_fallback",
        "image": "image_ocr",
        "rotate": "rotate_slide",
        "click": "click_coords",
        "text": "text_reasoning",
        "none": "none",
    }

    def __init__(
        self,
        detector: CaptchaDetector | None = None,
        jev_client: JevClient | None = None,
        heavy_families: list[str] | None = None,
    ) -> None:
        self._detector = detector or CaptchaDetector()
        self._jev = jev_client
        self._heavy = set(heavy_families or ["arkose", "geetest_v4", "recaptcha_enterprise"])

    def route(self, html: str, page_url: str = "") -> RoutingResult:
        """Detect and route the captcha in *html*.

        Args:
            html: Full page HTML or text snapshot.
            page_url: Optional URL for logging context.

        Returns:
            :class:`RoutingResult` with family, engine, and Jev confirmation flag.
        """
        detection = self._detector.detect(html)
        logger.info(
            "Triage[%s]: family=%s confidence=%.2f signatures=%s",
            page_url or "?",
            detection.family,
            detection.confidence,
            detection.matched_signatures,
        )

        # ----------------------------------------------------------------
        # Fast path: no captcha detected by DOM signatures
        # ----------------------------------------------------------------
        if not detection.detected:
            if self._jev and self._try_noul_gate(html):
                return RoutingResult(
                    family="none",
                    engine="none",
                    confidence=0.0,
                    jev_confirmed=True,
                    pre_gated_none=True,
                )
            return RoutingResult(
                family="none",
                engine="none",
                confidence=0.0,
                jev_confirmed=False,
                pre_gated_none=False,
            )

        # ----------------------------------------------------------------
        # Jev pre-gate: "Is there really no captcha?"
        # ----------------------------------------------------------------
        if self._jev and detection.confidence < 0.6 and self._try_noul_gate(html):
            logger.info("Jev pre-gate: no captcha confirmed (low confidence detection)")
            return RoutingResult(
                family="none",
                engine="none",
                confidence=detection.confidence,
                jev_confirmed=True,
                pre_gated_none=True,
            )

        # ----------------------------------------------------------------
        # Default engine from family map
        # ----------------------------------------------------------------
        default_engine = self._resolve_engine(detection)

        # ----------------------------------------------------------------
        # Jev choice: confirm engine
        # ----------------------------------------------------------------
        if self._jev:
            engine = self._try_jev_choice(html, detection, default_engine)
            return RoutingResult(
                family=detection.family,
                engine=engine,
                confidence=detection.confidence,
                jev_confirmed=True,
                pre_gated_none=False,
            )

        return RoutingResult(
            family=detection.family,
            engine=default_engine,
            confidence=detection.confidence,
            jev_confirmed=False,
            pre_gated_none=False,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_engine(self, detection: DetectionResult) -> str:
        """Map a detection family to its default engine key."""
        engine = self._FAMILY_ENGINE_MAP.get(detection.family, "api_fallback")
        # Override with api_fallback for configured heavy families
        if detection.family in self._heavy:
            engine = "api_fallback"
        return engine

    def _try_noul_gate(self, html: str) -> bool:
        """Ask Jev: "Is there no captcha here?" Returns True if clearly absent."""
        assert self._jev is not None
        try:
            answer: JevAnswerNoul = self._jev.noul(
                state=html[:4000],  # trim to save tokens
                name="no_captcha",
                instructions=(
                    "Does this page HTML contain NO captcha widget of any kind "
                    "(no reCAPTCHA, no hCaptcha, no Turnstile, no image puzzle, "
                    "no text challenge, no slider)?"
                ),
            )
            return answer.noul >= _NO_CAPTCHA_NOUL_THRESHOLD
        except (JevAuthError, JevServerError, JevResponseError) as exc:
            logger.warning("Jev noul gate failed (will skip): %s", exc)
            return False

    def _try_jev_choice(
        self,
        html: str,
        detection: DetectionResult,
        default_engine: str,
    ) -> str:
        """Ask Jev to confirm engine given DOM detection context."""
        assert self._jev is not None
        context = (
            f"Detected family: {detection.family} (confidence={detection.confidence:.2f}). "
            f"Signatures: {', '.join(detection.matched_signatures[:5])}.\n"
            f"Page snippet (first 2000 chars): {html[:2000]}"
        )
        try:
            answer = self._jev.choice(
                state=context,
                name="engine",
                instructions=(
                    "Based on the detected captcha family and page evidence, "
                    "which solver engine should be used?"
                ),
                criteria=_ENGINE_CRITERIA,
            )
            engine = answer.choice
            if engine not in _ENGINE_CRITERIA:
                logger.warning("Jev returned unknown engine %r — using default", engine)
                return default_engine
            logger.info("Jev engine choice: %s (prob=%.2f)", engine, answer.probability or 0.0)
            return engine
        except (JevAuthError, JevServerError, JevResponseError) as exc:
            logger.warning(
                "Jev choice failed (falling back to default %s): %s", default_engine, exc
            )
            return default_engine
