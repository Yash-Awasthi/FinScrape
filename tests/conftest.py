"""Shared test fixtures for scraper tests — resets circuit breakers."""
import os

import dotenv
import pytest

# Laya is an optional ~800MB model; tests must see the same chain CI does, without it.
os.environ["FINSCRAPE_LAYA"] = "0"

# A developer's .env must not decide what the tests see: finscrape.config calls
# load_dotenv() on import and server.settings reads .env directly.
dotenv.load_dotenv = lambda *args, **kwargs: False

try:
    from server.settings import Settings

    Settings.model_config["env_file"] = None
except ImportError:
    pass


@pytest.fixture(autouse=True)
def _reset_breakers():
    """Reset circuit breakers between tests so no test inherits a tripped breaker."""
    try:
        from finscrape.scrapers import reset_breakers
        reset_breakers()
    except ImportError:
        pass
    yield
    try:
        from finscrape.scrapers import reset_breakers
        reset_breakers()
    except ImportError:
        pass
