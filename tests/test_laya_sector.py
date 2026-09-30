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


def test_promoted_checkpoint_reloads_without_restart(tmp_path, monkeypatch):
    import os
    import sys
    import types

    from finscrape.analysis import laya

    weights = tmp_path / "model.safetensors"
    weights.write_text("a")
    loads = []
    fake = types.SimpleNamespace(Agent=lambda path: loads.append(path) or types.SimpleNamespace(predict=len(loads)))
    monkeypatch.setitem(sys.modules, "laya", fake)
    monkeypatch.setattr(laya, "_MODEL", str(tmp_path))
    monkeypatch.setattr(laya.sys, "platform", "win32")
    monkeypatch.delenv("FINSCRAPE_LAYA", raising=False)
    for name, value in (("_predict", None), ("_unavailable", False), ("_stamp", None)):
        monkeypatch.setattr(laya, name, value)

    assert laya._load() == 1 and laya._load() == 1
    weights.unlink()
    assert laya._load() == 1  # mid-swap: keep serving the old model
    weights.write_text("b")
    os.utime(weights, (1, 1))
    assert laya._load() == 2
