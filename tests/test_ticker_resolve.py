"""Tests for the one company->ticker map and its word-boundary matching.

Covers the exact failure modes that used to leak garbage tickers into
pipeline.py's valid_tickers gate: substring hits ("arm" inside "pharma",
"target" inside "price target", "citi" inside "Citizens Financial") and
real liquid tickers getting dropped by the stopword list (NOW, ALL, IT,
AI, KEY, GO, ONE).
"""

from finscrape.analysis.constants import TICKER_STOPWORDS
from finscrape.analysis.ticker_map import COMPANY_TO_TICKER, resolve_company_tickers
from finscrape.analysis.validator import clean_tickers
from finscrape.entity_map import _matches
from finscrape.scrapers import BaseScraper

# Same boundary-match rule nlp.py's analyst detection runs on ANALYST_ENTITIES —
# "citi" must only fire on the word "citi", never on the "citi" inside "Citizens".
_ANALYST_BANK_NAMES = ("citigroup", "citi", "goldman sachs", "morgan stanley")


def test_no_arm_from_pharma_substring():
    assert resolve_company_tickers("pharma pipeline update") == []


def test_no_tgt_from_price_target_substring():
    assert "TGT" not in resolve_company_tickers("analyst raised price target")


def test_dollar_now_kept_through_full_pipeline():
    tickers = BaseScraper.extract_tickers_from_text("$NOW beat estimates")
    assert "NOW" in tickers


def test_bare_now_dropped_through_full_pipeline():
    # "NOW" is a real ticker (ServiceNow) but also an ordinary English word —
    # only the explicit $NOW/(NOW) form should survive, never bare caps prose.
    tickers = BaseScraper.extract_tickers_from_text("Shares fell. Read the news NOW for details.")
    assert "NOW" not in tickers


def test_clean_tickers_keeps_dollar_prefixed_stopword():
    assert clean_tickers(["NOW"], text="$NOW beat estimates") == ["NOW"]


def test_clean_tickers_drops_bare_prose_stopword():
    assert clean_tickers(["OPEN"], text="markets open early today") == []


def test_ai_boom_headline_does_not_mint_ai_ticker():
    # "AI" the acronym shows up in caps constantly; without an explicit
    # $AI/(AI) marker that must not be read as the C3.ai ticker.
    tickers = BaseScraper.extract_tickers_from_text(
        "AI stocks surged today as investors bet on the AI boom"
    )
    assert "AI" not in tickers


def test_stopwords_still_gate_bare_mentions():
    for real_ticker in ("NOW", "ALL", "IT", "AI", "KEY", "GO", "ONE"):
        assert real_ticker in TICKER_STOPWORDS


def test_citizens_financial_not_tagged_analyst_bank():
    assert not any(_matches(a, "citizens financial") for a in _ANALYST_BANK_NAMES)
    assert any(_matches(a, "citigroup") for a in _ANALYST_BANK_NAMES)


def test_american_express_resolves_from_the_one_map():
    assert COMPANY_TO_TICKER["american express"] == "AXP"
    assert resolve_company_tickers("american express reported earnings") == ["AXP"]


def test_apple_and_apple_inc_are_one_entity():
    tickers = resolve_company_tickers("Apple reported earnings. Apple Inc. beat estimates.")
    assert tickers == ["AAPL"]


def test_bare_capitals_are_acronyms_not_tickers():
    text = (
        "the dean of the IE School said, citing ratings agency KBRA, that World War II "
        "debt levels were unmatched"
    )
    assert BaseScraper.extract_tickers_from_text(text) == []


def test_exchange_prefixed_symbol_is_a_ticker():
    assert "XYZ" in BaseScraper.extract_tickers_from_text("Block (NYSE: XYZ) rose 4%")
    assert "PLTR" in BaseScraper.extract_tickers_from_text("Palantir NASDAQ:PLTR jumped")


def test_parenthesised_acronyms_are_not_tickers_unless_listed():
    text = "Rapid Support Forces (RSF) clashed near El Fasher, the UN (OCHA) said; Apple (AAPL) fell"
    tickers = BaseScraper.extract_tickers_from_text(text)
    assert "AAPL" in tickers
    assert "RSF" not in tickers and "OCHA" not in tickers
