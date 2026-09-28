"""Global exchange registry + keyless multi-market quotes.

WorldFin tracks what events do to markets EVERYWHERE — so the market-data layer
must speak every major exchange, not just NYSE. This module maps ~25 exchanges
to their Yahoo Finance symbol suffixes (one interface, all markets) and ships
dedicated keyless adapters for the markets where Yahoo is slow or blocked
(China via Eastmoney/Sina, exactly the endpoints our absorbed reference repos —
tradingagents-ashare, qlib, deepear — use).

Design:
- Pure/parsable parts (registry integrity, symbol resolution, adapter parsing)
  are unit-testable offline; network parts degrade to empty results, never raise.
- Quotes come back normalized: {symbol, price, change_pct, currency?, source}.

Usage:
    from finscrape.market_data.exchanges import get_global_quotes, resolve_symbol
    get_global_quotes([("NSE", "RELIANCE"), ("SSE", "600519")])   # across markets
"""

from __future__ import annotations

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 10


@dataclass(frozen=True)
class Exchange:
    code: str          # canonical short code, e.g. "NSE"
    name: str
    country: str
    yf_suffix: str     # Yahoo Finance suffix, "" for US
    currency: str
    sina_prefix: str = ""   # Sina quote prefix (China only)
    em_market: int | None = None  # Eastmoney market id (0=SZ, 1=SH)


# The registry. yf_suffix "" = plain ticker (US). Values verified against Yahoo's
# symbol conventions; China carries dedicated keyless adapters below.
EXCHANGES: dict[str, Exchange] = {
    e.code: e
    for e in [
        Exchange("NYSE", "New York Stock Exchange", "US", "", "USD"),
        Exchange("NASDAQ", "Nasdaq", "US", "", "USD"),
        Exchange("AMEX", "NYSE American", "US", "", "USD"),
        Exchange("NSE", "National Stock Exchange of India", "IN", ".NS", "INR"),
        Exchange("BSE", "Bombay Stock Exchange", "IN", ".BO", "INR"),
        Exchange("SSE", "Shanghai Stock Exchange", "CN", ".SS", "CNY", sina_prefix="sh", em_market=1),
        Exchange("SZSE", "Shenzhen Stock Exchange", "CN", ".SZ", "CNY", sina_prefix="sz", em_market=0),
        Exchange("HKEX", "Hong Kong Exchange", "HK", ".HK", "HKD"),
        Exchange("TSE", "Tokyo Stock Exchange", "JP", ".T", "JPY"),
        Exchange("KRX", "Korea Exchange", "KR", ".KS", "KRW"),
        Exchange("KOSDAQ", "KOSDAQ", "KR", ".KQ", "KRW"),
        Exchange("TWSE", "Taiwan Stock Exchange", "TW", ".TW", "TWD"),
        Exchange("SGX", "Singapore Exchange", "SG", ".SI", "SGD"),
        Exchange("ASX", "Australian Securities Exchange", "AU", ".AX", "AUD"),
        Exchange("TSX", "Toronto Stock Exchange", "CA", ".TO", "CAD"),
        Exchange("B3", "B3 — Brasil Bolsa Balcão", "BR", ".SA", "BRL"),
        Exchange("LSE", "London Stock Exchange", "GB", ".L", "GBp"),
        Exchange("XETRA", "Deutsche Börse Xetra", "DE", ".DE", "EUR"),
        Exchange("EURONEXT_PARIS", "Euronext Paris", "FR", ".PA", "EUR"),
        Exchange("EURONEXT_AMS", "Euronext Amsterdam", "NL", ".AS", "EUR"),
        Exchange("EURONEXT_BRU", "Euronext Brussels", "BE", ".BR", "EUR"),
        Exchange("BME", "Bolsa de Madrid", "ES", ".MC", "EUR"),
        Exchange("BorsaItaliana", "Borsa Italiana Milan", "IT", ".MI", "EUR"),
        Exchange("SIX", "SIX Swiss Exchange", "CH", ".SW", "CHF"),
        Exchange("Tadawul", "Saudi Exchange", "SA", ".SR", "SAR"),
        Exchange("BIST", "Borsa Istanbul", "TR", ".IS", "TRY"),
        Exchange("IDX", "Indonesia Stock Exchange", "ID", ".JK", "IDR"),
        Exchange("SET", "Stock Exchange of Thailand", "TH", ".BK", "THB"),
    ]
}

# Benchmark indices per market (Yahoo symbols) — tracked alongside stocks.
INDICES: dict[str, str] = {
    "US": "^GSPC", "IN": "^NSEI", "CN": "000001.SS", "HK": "^HSI", "JP": "^N225",
    "KR": "^KS11", "TW": "^TWII", "AU": "^AXJO", "CA": "^GSPTSE", "BR": "^BVSP",
    "GB": "^FTSE", "DE": "^GDAXI", "FR": "^FCHI", "EU": "^STOXX50E", "SA": "^TASI.SR",
}

_SUFFIX_TO_CODE = {e.yf_suffix: code for code, e in EXCHANGES.items() if e.yf_suffix}


def detect_exchange(symbol: str) -> str | None:
    """Exchange code inferred from an explicit Yahoo suffix ('600519.SS' → SSE)."""
    m = re.search(r"\.([A-Z]{1,4})$", symbol.strip().upper())
    return _SUFFIX_TO_CODE.get(f".{m.group(1)}") if m else None


def resolve_symbol(symbol: str, exchange: str | None = None) -> str:
    """Bare ticker + exchange code → Yahoo symbol ('RELIANCE', 'NSE' → 'RELIANCE.NS').

    Symbols that already carry a known suffix pass through untouched. US tickers
    (or unknown exchanges) return the bare symbol, matching Yahoo's convention.
    """
    symbol = symbol.strip().upper()
    if detect_exchange(symbol):
        return symbol
    code = (exchange or "").upper()
    if code in EXCHANGES and EXCHANGES[code].yf_suffix:
        return symbol + EXCHANGES[code].yf_suffix
    return symbol


# ---------------------------------------------------------------------------
# China realtime adapters (keyless) — endpoints from our absorbed reference tree
# ---------------------------------------------------------------------------

_SINA_HEADERS = {"Referer": "https://finance.sina.com.cn/", "User-Agent": "Mozilla/5.0"}


def _sina_code(symbol: str, exchange: Exchange) -> str | None:
    """'600519' on SSE → 'sh600519'; Beijing (4/8-prefix) → 'bj...'."""
    code = symbol.strip().lower()
    if code.startswith(("4", "8")):
        return f"bj{code}"
    if exchange.sina_prefix:
        return f"{exchange.sina_prefix}{code}"
    return None


def parse_sina_quotes(body: str, symbol_by_sina_code: dict[str, str]) -> dict[str, dict]:
    """Parse Sina hq.sinajs.cn GBK response lines → normalized quotes.

    Pure function (unit-tested). Field map: 1 open, 2 prev_close, 3 price,
    4 high, 5 low, 8 volume, 9 amount, 30/31 date/time.
    """
    out: dict[str, dict] = {}
    for line in body.splitlines():
        line = line.strip()
        if '="' not in line:
            continue
        var_part, data_part = line.split('="', 1)
        sina_code = var_part.split("_")[-1]
        original = symbol_by_sina_code.get(sina_code)
        if not original:
            continue
        fields = data_part.rstrip('";').split(",")
        if len(fields) < 10:
            continue

        def _f(idx: int, *, _fields: list[str] = fields) -> float | None:
            try:
                return float(_fields[idx])
            except (ValueError, IndexError):
                return None

        price, prev = _f(3), _f(2)
        out[original] = {
            "symbol": original,
            "price": price,
            "previous_close": prev,
            "change_pct": round((price - prev) / prev * 100, 2) if price and prev else None,
            "source": "sina",
        }
    return out


def fetch_china_quotes(symbols: list[tuple[str, str]]) -> dict[str, dict]:
    """Realtime quotes for China A-shares, keyless.

    Eastmoney (JSON) first — the same push2 API qlib/deepear scrape — with Sina
    as fallback. `symbols`: (exchange_code, bare_code) pairs, exchange SSE|SZSE.
    """
    em_secids: list[str] = []
    em_symbol_by_secid: dict[str, str] = {}
    sina_codes: list[str] = []
    sina_symbol_by_code: dict[str, str] = {}

    for exchange_code, symbol in symbols:
        exchange = EXCHANGES.get(exchange_code.upper())
        if not exchange or exchange.em_market is None:
            continue
        code = symbol.strip().lower()
        if not re.fullmatch(r"\d{6}", code):
            continue
        secid = f"{exchange.em_market}.{code}"
        em_secids.append(secid)
        em_symbol_by_secid[secid] = f"{code}{exchange.yf_suffix}"
        sina = _sina_code(code, exchange)
        if sina:
            sina_codes.append(sina)
            sina_symbol_by_code[sina] = f"{code}{exchange.yf_suffix}"

    if not em_secids and not sina_codes:
        return {}

    # Eastmoney primary
    if em_secids:
        try:
            resp = requests.get(
                "https://push2.eastmoney.com/api/qt/ulist.np/get",
                params={"fltt": 2, "secids": ",".join(em_secids),
                        "fields": "f2,f3,f12,f14,f18"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json().get("data") or {}
            out: dict[str, dict] = {}
            for diff in data.get("diff") or []:
                symbol = em_symbol_by_secid.get(str(diff.get("f12", "")))
                if not symbol:
                    continue
                out[symbol] = {
                    "symbol": symbol,
                    "price": diff.get("f2") if isinstance(diff.get("f2"), (int, float)) else None,
                    "change_pct": diff.get("f3") if isinstance(diff.get("f3"), (int, float)) else None,
                    "name": diff.get("f14"),
                    "source": "eastmoney",
                }
            if out:
                return out
        except (requests.RequestException, ValueError) as e:
            logger.warning("eastmoney quotes failed: %s", e)

    # Sina fallback
    if sina_codes:
        try:
            resp = requests.get(
                "https://hq.sinajs.cn/list=" + ",".join(sina_codes),
                headers=_SINA_HEADERS,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            resp.encoding = "gbk"
            return parse_sina_quotes(resp.text, sina_symbol_by_code)
        except requests.RequestException as e:
            logger.warning("sina quotes failed: %s", e)

    return {}


# ---------------------------------------------------------------------------
# Global quotes via Yahoo (covers every registered exchange)
# ---------------------------------------------------------------------------

# The tape, watchlist and markets panels ask for overlapping symbols within seconds.
_QUOTE_TTL_S = 30.0
_quote_cache: dict[str, tuple[float, dict]] = {}


def _yahoo_quote(sym: str) -> dict | None:
    try:
        import yfinance as yf

        fast = yf.Ticker(sym).fast_info
        price, prev = fast.last_price, fast.previous_close
        return {
            "symbol": sym,
            "price": float(price) if price is not None else None,
            "change_pct": round((float(price) - float(prev)) / float(prev) * 100, 2)
            if price and prev
            else None,
            "currency": getattr(fast, "currency", None) or None,
            "source": "yahoo",
        }
    except Exception as e:  # noqa: BLE001 — one bad ticker never kills the batch
        logger.warning("yahoo quote %s failed: %s", sym, e)
        return None


def get_global_quotes(
    wanted: list[tuple[str, str]],
    *,
    prefer_native_cn: bool = True,
) -> dict[str, dict]:
    """Normalized quotes across all markets.

    `wanted`: (exchange_code, bare_symbol) pairs. Chinese A-shares go through
    the keyless Eastmoney/Sina adapters when `prefer_native_cn` (faster than
    Yahoo there); everything else rides Yahoo Finance in a thread fan-out, cached briefly.
    """
    now = time.monotonic()
    out: dict[str, dict] = {}
    cn: list[tuple[str, str]] = []
    yahoo: list[str] = []

    for exchange_code, symbol in wanted:
        code = exchange_code.upper()
        key = resolve_symbol(symbol, code)
        hit = _quote_cache.get(key)
        if hit and now - hit[0] < _QUOTE_TTL_S:
            out[key] = hit[1]
        elif code in ("SSE", "SZSE") and prefer_native_cn:
            cn.append((code, symbol))
        else:
            yahoo.append(key)

    fetched: dict[str, dict] = {}
    # One HTTP round trip per Yahoo symbol plus the China batch; run them together.
    with ThreadPoolExecutor(max_workers=8) as pool:
        china = pool.submit(fetch_china_quotes, cn) if cn else None
        for sym, quote in zip(yahoo, pool.map(_yahoo_quote, yahoo)):
            if quote:
                fetched[sym] = quote
        if china:
            try:
                fetched.update(china.result())
            except Exception as e:  # noqa: BLE001 — adapters degrade, never raise
                logger.warning("china adapter failed: %s", e)
    for key, quote in fetched.items():
        _quote_cache[key] = (now, quote)
    out.update(fetched)
    return out


def market_status(exchange_code: str, now_local_hour: int | None = None) -> str:
    """Coarse open/closed hint for UI badges (pure; hours are approximations).

    Uses the machine's local clock for the exchange's typical 9:30–16:00 trading
    day unless the caller supplies `now_local_hour`. Deliberately simple — the
    definitive source should be a sessions calendar later.
    """
    if exchange_code.upper() not in EXCHANGES:
        return "unknown"
    fake_hour = os.environ.get("FAKE_HOUR")
    hour = now_local_hour if now_local_hour is not None else (int(fake_hour) if fake_hour else None)
    if hour is None or hour < 0:
        return "unknown"
    return "open" if 9 <= hour < 16 else "closed"
