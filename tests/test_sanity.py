from komdigi_bot import __version__
from komdigi_bot.config import get_settings


def test_version():
    assert __version__ == "1.2.0"


def test_settings_default_solver_policy():
    assert get_settings().solver_policy == "hybrid"
