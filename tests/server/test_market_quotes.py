"""Live market quotes: shape, change calculation, and the 60 s cache."""

from __future__ import annotations

import pandas as pd

import finscrape.market_data as md


def _frame() -> pd.DataFrame:
    index = pd.DatetimeIndex(
        [
            "2026-11-20 20:00:00+00:00",  # previous session
            "2026-11-23 10:00:00+00:00",
            "2026-11-23 11:00:00+00:00",
        ]
    )
    fields = ["Open", "High", "Low", "Close", "Volume"]
    columns = pd.MultiIndex.from_product(
        [["AAPL", "MSFT"], fields], names=["Ticker", "Price"]
    )
    frame = pd.DataFrame(index=index, columns=columns, dtype=float)
    frame[("AAPL", "Close")] = [100.0, 105.0, 110.0]
    frame[("MSFT", "Close")] = [200.0, 195.0, 190.0]
    return frame


def test_quotes_use_the_previous_session_close(monkeypatch):
    monkeypatch.setattr(md.yf, "download", lambda **_kwargs: _frame())
    md.clear_quote_cache()

    rows = {q["symbol"]: q for q in md.get_quotes(["AAPL", "MSFT"])}

    assert rows["AAPL"]["previous_close"] == 100.0
    assert rows["AAPL"]["price"] == 110.0
    assert rows["AAPL"]["change_percent"] == 10.0
    assert rows["MSFT"]["change_percent"] == -5.0
    assert rows["AAPL"]["spark"] == [100.0, 105.0, 110.0]


def test_quotes_are_cached_per_symbol(monkeypatch):
    calls: list[str] = []

    def download(**kwargs):
        calls.append(kwargs["tickers"])
        return _frame()

    monkeypatch.setattr(md.yf, "download", download)
    md.clear_quote_cache()

    assert len(md.get_quotes(["AAPL"])) == 1
    assert len(md.get_quotes(["AAPL"])) == 1
    assert calls == ["AAPL"], "second call must be served from the quote cache"


def test_quotes_degrade_to_empty_without_a_download(monkeypatch):
    def boom(**_kwargs):
        raise RuntimeError("yfinance down")

    monkeypatch.setattr(md.yf, "download", boom)
    md.clear_quote_cache()

    assert md.get_quotes(["AAPL"]) == []
    assert md.get_quotes([]) == []


def test_quotes_skip_a_ticker_absent_from_the_frame(monkeypatch):
    monkeypatch.setattr(md.yf, "download", lambda **_kwargs: _frame())
    md.clear_quote_cache()

    assert md.get_quotes(["AAPL", "ZZZZ"]) == [md.get_quotes(["AAPL"])[0]]
