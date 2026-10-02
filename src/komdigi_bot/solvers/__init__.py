"""Solvers sub-package."""

from komdigi_bot.solvers.base import BaseSolver, SolveAttempt, SolveStatus
from komdigi_bot.solvers.checkbox_grid import CheckboxGridSolver
from komdigi_bot.solvers.click_coords import ClickCoordsSolver
from komdigi_bot.solvers.image_ocr import ImageOCRSolver
from komdigi_bot.solvers.llm import (
    LLMAPIError,
    LLMClient,
    LLMConfigError,
    LLMParseError,
    llm_from_settings,
)
from komdigi_bot.solvers.rotate_slide import RotateSlideSolver
from komdigi_bot.solvers.text_reasoning import TextReasoningSolver

__all__ = [
    "BaseSolver",
    "CheckboxGridSolver",
    "ClickCoordsSolver",
    "ImageOCRSolver",
    "LLMAPIError",
    "LLMClient",
    "LLMConfigError",
    "LLMParseError",
    "RotateSlideSolver",
    "SolveAttempt",
    "SolveStatus",
    "TextReasoningSolver",
    "llm_from_settings",
]
