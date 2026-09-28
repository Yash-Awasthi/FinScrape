"""Offline tests for the global exchange registry and its adapters."""

import pytest

from finscrape.exchanges import (
    EXCHANGES,
    INDICES,
    detect_exchange,
    fetch_china_quotes,
    get_global_quotes,
    market_status,
    parse_sina_quotes,
    resolve_symbol,
)

# ── registry integrity ───────────────────────────────────────────────────────

def test_registry_covers_all_majors():
    for code in ("NYSE", "NASDAQ", "NSE", "BSE", "SSE", "SZSE", "HKEX", "TSE",
                 "KRX", "LSE", "XETRA", "EURONEXT_PARIS", "ASX", "TSX", "B3",
                 "SGX", "TWSE", "Tadawul", "BIST", "IDX"):
        assert code in EXCHANGES, f"{code} missing from exchange registry"


def test_registry_fields_consistent():
    for code, exchange in EXCHANGES.items():
        assert exchange.code == code
        assert exchange.yf_suffix == "" or re.match(r"^\.[A-Z]{1,4}$", exchange.yf_suffix)
        assert exchange.currency
        # suffixes are unique across the registry
    suffixes = [e.yf_suffix for e in EXCHANGES.values() if e.yf_suffix]
    assert len(suffixes) == len(set(suffixes))


import re


def test_indices_reference_known_markets():
    for market in INDICES:
        assert market in {e.country for e in EXCHANGES.values()} | {"EU"}


# ── symbol resolution ────────────────────────────────────────────────────────

def test_resolve_symbol_adds_suffix():
    assert resolve_symbol("RELIANCE", "NSE") == "RELIANCE.NS"
    assert resolve_symbol("RELIANCE", "BSE") == "RELIANCE.BO"
    assert resolve_symbol("600519", "SSE") == "600519.SS"
    assert resolve_symbol("000001", "SZSE") == "000001.SZ"
    assert resolve_symbol("0700", "HKEX") == "0700.HK"
    assert resolve_symbol("7203", "TSE") == "7203.T"
    assert resolve_symbol("SAP", "XETRA") == "SAP.DE"


def test_resolve_symbol_passes_through_suffixed():
    assert resolve_symbol("600519.SS") == "600519.SS"
    assert resolve_symbol("RELIANCE.NS", "BSE") == "RELIANCE.NS"


def test_resolve_symbol_us_stays_bare():
    assert resolve_symbol("AAPL", "NYSE") == "AAPL"
    assert resolve_symbol("MSFT", "") == "MSFT"
    assert resolve_symbol("AAPL", "MARS") == "AAPL"  # unknown exchange → bare


def test_detect_exchange():
    assert detect_exchange("RELIANCE.NS") == "NSE"
    assert detect_exchange("600519.SS") == "SSE"
    assert detect_exchange("AAPL") is None


# ── sina adapter parser (pure) ───────────────────────────────────────────────

def test_parse_sina_quotes():
    body = (
        'var hq_str_sh600519="贵州茅台,1700.00,1680.00,1712.50,1715.00,1698.00,'
        '1712.00,1713.00,2000000,342000000000,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-09-04,15:00:00,00";\n'
        'var hq_str_sz000001="平安银行,11.00,10.90,11.05,11.10,10.95,'
        '11.04,11.05,9000000,99500000,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-09-04,15:00:00,00";'
    )
    mapping = {"sh600519": "600519.SS", "sz000001": "000001.SZ"}
    out = parse_sina_quotes(body, mapping)
    assert out["600519.SS"]["price"] == pytest.approx(1712.50)
    assert out["600519.SS"]["change_pct"] == pytest.approx(1.93, abs=0.01)
    assert out["000001.SZ"]["previous_close"] == pytest.approx(10.90)


def test_parse_sina_quotes_ignores_malformed_lines():
    out = parse_sina_quotes('var hq_str_sh600519="too,short";\ngarbage line', {"sh600519": "600519.SS"})
    assert out == {}


# ── china adapter: graceful degradation, no raise ────────────────────────────

def test_fetch_china_quotes_empty_on_bad_input():
    assert fetch_china_quotes([("SSE", "NOT_A_CODE")]) == {}
    assert fetch_china_quotes([("NYSE", "600519")]) == {}  # not a China exchange


def test_market_status_coarse():
    assert market_status("NSE", 10) == "open"
    assert market_status("NSE", 20) == "closed"
    assert market_status("MARS") == "unknown"


# ── global fan-out (network; tolerate sandboxed CI) ──────────────────────────

def test_get_global_quotes_never_raises():
    out = get_global_quotes([("SSE", "600519"), ("NYSE", "AAPL")])
    assert isinstance(out, dict)  # contents depend on network availability


def test_yahoo_quotes_fan_out_and_cache(monkeypatch):
    import threading
    import time

    from finscrape import exchanges

    exchanges._quote_cache.clear()
    calls: list[str] = []
    active, peak = [0], [0]
    lock = threading.Lock()

    def fake_one(sym):
        with lock:
            calls.append(sym)
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return {"symbol": sym, "price": 1.0, "change_pct": 0.0, "currency": "USD", "source": "yahoo"}

    monkeypatch.setattr(exchanges, "_yahoo_quote", fake_one)
    syms = [("", s) for s in ("AAPL", "MSFT", "NVDA", "JPM", "XOM", "SHEL.L")]
    assert len(exchanges.get_global_quotes(syms)) == 6
    assert peak[0] > 1  # fetched concurrently, not one after another
    exchanges.get_global_quotes(syms[:3])
    assert len(calls) == 6  # the second call is served from the cache
