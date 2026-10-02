"""Config schema tests: defaults, YAML fixture loading, precedence, structured errors."""

from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

from komdigi_bot.config import Settings


def _settings_with_yaml(tmp_path: Path, content: str) -> Settings:
    """Build a Settings subclass pointed at a fixture YAML file."""
    yaml_path = tmp_path / "fixture.yaml"
    _ = yaml_path.write_text(content, encoding="utf-8")

    class FixtureSettings(Settings):
        model_config: ClassVar[SettingsConfigDict] = {
            **Settings.model_config,  # type: ignore[arg-type]
            "yaml_file": str(yaml_path),
        }

    return FixtureSettings()


def test_repo_config_defaults_load() -> None:
    settings = Settings()
    assert settings.solver_policy == "hybrid"
    assert settings.heavy_families == ["arkose", "geetest_v4", "recaptcha_enterprise"]
    assert settings.interval_seconds == 1800
    assert settings.jitter_seconds == 180
    assert settings.stealth.headless is True
    assert settings.stealth.session_rotation is True
    assert settings.stealth.min_delay_ms == 500
    assert settings.jev.endpoint == "https://api.typesafe.ai/v1/systemone"
    assert settings.jev.model == "jev-latest"
    assert settings.retry.max_attempts >= 1


def test_yaml_fixture_overrides_defaults(tmp_path: Path) -> None:
    settings = _settings_with_yaml(tmp_path, "solver_policy: inhouse\ninterval_seconds: 60\n")
    assert settings.solver_policy == "inhouse"
    assert settings.interval_seconds == 60


def test_env_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLVER_POLICY", "api_first")
    settings = _settings_with_yaml(tmp_path, "solver_policy: inhouse\n")
    assert settings.solver_policy == "api_first"


def test_type_mismatch_yaml_raises_validation_error(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _ = _settings_with_yaml(tmp_path, "stealth: 123\n")
