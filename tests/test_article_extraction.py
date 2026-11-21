"""Article extraction: trafilatura must return the body, never the nav (plan M1.5).

The ten pages in `tests/fixtures/extraction/` are synthetic-but-realistic templates
(one per news-site shape: wire, broadcaster, paywalled daily, live blog, terminal,
weekly essay, ad-heavy local paper). Each carries the same six-sentence body under a
loud chrome of nav links, a cookie banner, an ad, a related-links rail and a footer.

No network: the fixtures are the pages. If trafilatura ever starts shipping chrome,
these fail with the offending line quoted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

trafilatura = pytest.importorskip("trafilatura")

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "extraction"
PAGES = sorted(FIXTURES.glob("*.html"))

# Chrome that must never reach the model: nav labels, the cookie banner, the ad rail.
CHROME = [
    "Cookie policy",
    "Accept all",
    "Trade now with zero commission",
    "Related",
    "Careers",
    "Sign in",
    "Subscribe",
]


def _extract(path: Path) -> str:
    return trafilatura.extract(path.read_text(encoding="utf-8")) or ""


def test_the_fixture_set_covers_ten_pages():
    assert len(PAGES) == 10, [p.name for p in PAGES]


@pytest.mark.parametrize("page", PAGES, ids=[p.stem for p in PAGES])
def test_main_text_is_extracted_without_the_chrome(page: Path):
    text = _extract(page)
    # The body: every one of the six sentences, in the page's own slug.
    for i in range(1, 7):
        assert f"Sentence {i} of the {page.stem} article body" in text, page.stem
    assert "Policymakers voted seven to two for the increase, citing wage growth." in text
    assert len(text) >= 700, (page.stem, len(text))
    # The chrome: none of it.
    for marker in CHROME:
        assert marker not in text, f"{page.stem} leaked {marker!r}"


def test_extraction_returns_text_not_markup():
    text = _extract(PAGES[0])
    assert "<p>" not in text and "</div>" not in text
