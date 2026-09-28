"""`laya.choose_sector`: how LLM, Laya, keyword and company evidence combine."""

from finscrape.analysis.laya import LayaView, choose_sector
from finscrape.analysis.sectors import TAXONOMY
from finscrape.analysis.ticker_map import COMPANY_TO_TICKER, TICKER_SECTOR

view_other = LayaView("financials", 0.2, "neutral", 0.4)


def test_company_ticker_supports_llm_technology():
    assert choose_sector("technology", view_other, "", tickers=["AMD"]) == "technology"


def test_political_story_without_tickers_stays_other():
    assert choose_sector("technology", view_other, "") == "other"
    assert choose_sector("technology", view_other, "", tickers=[]) == "other"


def test_non_tech_company_does_not_support_technology():
    assert choose_sector("technology", view_other, "", tickers=["LMT"]) == "industrials"


def test_company_sector_is_the_fallback_before_other():
    assert choose_sector("", view_other, "", tickers=["AMZN"]) == "technology"
    assert choose_sector("", None, "", tickers=["XOM", "CVX", "AMD"]) == "energy"
    assert choose_sector("", None, "", tickers=["SPY"]) == "other"


def test_tied_companies_give_no_sector():
    assert choose_sector("", None, "", tickers=["WMT", "UBER"]) == "other"


def test_keywords_still_outrank_company_sector():
    assert choose_sector("", None, "energy", tickers=["AMD"]) == "energy"


def test_every_mapped_company_has_a_sector():
    assert set(COMPANY_TO_TICKER.values()) <= set(TICKER_SECTOR)
    assert set(TICKER_SECTOR.values()) <= set(TAXONOMY) - {"other"}
