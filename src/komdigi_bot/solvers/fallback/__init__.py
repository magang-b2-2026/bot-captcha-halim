"""Fallback sub-package — 2captcha API client and dispatcher."""

from komdigi_bot.solvers.fallback.api_solver import APIFallbackSolver, api_fallback_solver_from_page
from komdigi_bot.solvers.fallback.twocaptcha import (
    TwoCaptchaClient,
    TwoCaptchaError,
    TwoCaptchaTimeout,
)

__all__ = [
    "APIFallbackSolver",
    "TwoCaptchaClient",
    "TwoCaptchaError",
    "TwoCaptchaTimeout",
    "api_fallback_solver_from_page",
]
