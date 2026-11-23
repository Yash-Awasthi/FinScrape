"""Back-compat shim: fetchers moved in plan M3.4 (`finscrape/fetchers/`).

Old import paths keep working for anything outside this repository (a script, a
notebook); nothing inside it should use them — `tests/test_package_layout.py` says so.
"""

from finscrape.fetchers import *  # noqa: F403
from finscrape.fetchers import (  # noqa: F401
    MAX_AGE_HOURS,
    MAX_PARAGRAPHS,
    MAX_WORDS,
    MIN_TEXT_LENGTH,
    BaseScraper,
)
