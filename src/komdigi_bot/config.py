"""Application settings.

Schema ported from communiteyes-pro ``config.yaml`` (scraper stealth + scheduling
sections) and extended with the KOMDIGI captcha computer-use bot sections
(Jev decision endpoint, solver policy, retry ladder).

Precedence (highest first): init kwargs > environment variables > ``.env`` >
``config/config.yaml`` > field defaults. Secrets (API keys) are flat env-facing
fields that mirror ``.env.example`` names exactly and are never defaulted.
"""

from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)
from typing_extensions import override

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_YAML = _REPO_ROOT / "config" / "config.yaml"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


class StealthConfig(BaseModel):
    """Stealth browser options (ported from communiteyes-pro scraper.stealth)."""

    headless: bool = True
    viewport_width: int = 1280
    viewport_height: int = 800
    user_agent: str = DEFAULT_USER_AGENT
    min_delay_ms: int = 500
    max_delay_ms: int = 3000
    scroll_pages: int = 3
    session_rotation: bool = True
    proxy: str = ""


class JevConfig(BaseModel):
    """TypeSafe AI System One (Jev) decision endpoint settings."""

    endpoint: str = "https://api.typesafe.ai/v1/systemone"
    model: str = "jev-latest"
    timeout_seconds: int = 30


class RetryConfig(BaseModel):
    """Retry ladder pacing."""

    max_attempts: int = 4
    backoff_base_seconds: float = 2.0


class Settings(BaseSettings):
    """Root settings for the KOMDIGI captcha computer-use bot."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        yaml_file=_CONFIG_YAML,
        yaml_file_encoding="utf-8",
        extra="ignore",
    )

    solver_policy: str = "hybrid"
    heavy_families: list[str] = Field(
        default_factory=lambda: ["arkose", "geetest_v4", "recaptcha_enterprise"]
    )
    interval_seconds: int = 1800
    jitter_seconds: int = 180

    typesafe_api_key: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model_vision: str = ""
    llm_model_reasoning: str = ""
    twocaptcha_api_key: str = ""        # 2captcha.com API key (for api_fallback engine)
    solver_api_key_2captcha: str = ""   # legacy alias kept for backward compat

    stealth: StealthConfig = Field(default_factory=StealthConfig)
    jev: JevConfig = Field(default_factory=JevConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)

    @override
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Order sources: init > env > .env > config.yaml > secrets > defaults."""
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the cached process-wide settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
