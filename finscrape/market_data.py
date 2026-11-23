"""
Market data fetching via yfinance.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import time
from typing import cast

import pandas as pd
import yfinance as yf

from finscrape.settings import env_float

logger = logging.getLogger(__name__)

# Per-process TTL cache so the worker's per-article calls (and the correlation pass)
# don't re-hit yfinance for the same ticker every time (Phase 12 / RISKS R1 hot-path).
# Keyed by ticker → (result_dict, monotonic_ts). TTL via FINSCRAPE_MARKET_TTL (seconds).
_cache: dict[str, tuple[dict, float]] = {}

# Quotes for the live market panel. Intraday bars are far cheaper than 1y history
# but still too heavy to fetch on every 60 s poll, so this cache is deliberately
# short (FINSCRAPE_QUOTE_TTL, default 60 s) and separate from the worker's quote TTL.
_quote_cache: dict[str, tuple[dict, float]] = {}

# Separate TTL cache for indicator facts (1y history per ticker, pricier fetch
# than the 2-day quote above) — same ticker → (result_dict, monotonic_ts) shape.
_indicator_cache: dict[str, tuple[dict, float]] = {}

# One-day reaction cache (price move + volume/dollar-volume vs the 20-day norm).
# The worker analyzes several articles per cycle; this keeps it to one batched
# download per symbol per TTL window.
_reaction_cache: dict[str, tuple[dict, float]] = {}


def _ttl() -> float:
    try:
        return env_float("FINSCRAPE_MARKET_TTL", 600.0)
    except ValueError:
        return 600.0


def clear_market_cache() -> None:
    """Drop the in-process market cache (used by tests)."""
    _cache.clear()


def clear_quote_cache() -> None:
    """Drop the live-quote cache and the failure window (tests, and a manual refresh).

    The failure window is part of the same upstream state: leaving it behind would make a
    refresh keep skipping a symbol that *just* started working again.
    """
    _quote_cache.clear()
    _quote_failures.clear()


def _quote_ttl() -> float:
    try:
        return env_float("FINSCRAPE_QUOTE_TTL", 60.0)
    except ValueError:
        return 60.0


def clear_indicator_cache() -> None:
    """Drop the in-process indicator cache (used by tests)."""
    _indicator_cache.clear()


def clear_reaction_cache() -> None:
    """Drop the one-day market-reaction cache (used by tests)."""
    _reaction_cache.clear()


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    """One column as a Series.

    pandas-stubs types `DataFrame.__getitem__` as a union that includes ndarray, so every
    `.iloc` / `.dropna` / `.reindex` on a column would fail to type-check. yfinance returns
    plain Series for these columns, which is the type this cast records.
    """
    return cast("pd.Series", frame[name])


def _symbol_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """The per-symbol sub-frame of a multi-ticker download."""
    return cast("pd.DataFrame", frame[symbol])


def _fetch(tickers: list[str]) -> dict[str, dict]:
    """One batched yfinance call for `tickers` → {ticker: result_dict}. Degrades to {}
    on any error so a slow/dead yfinance never crashes the cycle (it just skips boost)."""
    out: dict[str, dict] = {}
    try:
        df = yf.download(
            tickers=" ".join(tickers), period="2d", interval="1d", progress=False
        )
        if df is None or df.empty or "Close" not in df.columns:
            return out
        for t in tickers:
            try:
                close = (
                    _column(_symbol_frame(df, "Close"), t)
                    if len(tickers) > 1
                    else _column(df, "Close")
                )
                if len(close) < 2:
                    continue
                price = float(close.iloc[-1])
                prev = float(close.iloc[-2])
                if math.isnan(price) or math.isnan(prev) or prev == 0:
                    continue
                change = ((price - prev) / prev) * 100
                out[t] = {
                    "ticker": t,
                    "price": round(price, 2),
                    "change_percent": round(change, 2),
                }
            except Exception:
                continue
    except Exception as e:
        logger.warning("Market data error: %s", e)
    return out


def get_market_data(tickers: list[str]) -> list[dict]:
    """Fetch 2-day % change per ticker, served from a TTL cache. Only tickers whose
    cache entry is missing/stale are fetched (in one batched call). Returns a list of
    {"ticker", "price", "change_percent"} for the tickers that resolved."""
    tickers = [t for t in tickers if isinstance(t, str) and t]
    if not tickers:
        return []

    now = time.monotonic()
    ttl = _ttl()
    fresh: dict[str, dict] = {}
    stale: list[str] = []
    for t in dict.fromkeys(tickers):  # de-dupe, preserve order
        entry = _cache.get(t)
        if entry and (now - entry[1]) < ttl:
            fresh[t] = entry[0]
        else:
            stale.append(t)

    if stale:
        fetched = _fetch(stale)
        for t, result in fetched.items():
            _cache[t] = (result, now)
            fresh[t] = result

    return [fresh[t] for t in dict.fromkeys(tickers) if t in fresh]


def _close_series(df: pd.DataFrame, symbol: str) -> pd.Series | None:
    """Close column for one symbol from a single- or multi-ticker download."""
    try:
        if isinstance(df.columns, pd.MultiIndex):
            series = df[symbol]["Close"]
        elif "Close" in df.columns:
            series = df["Close"]
        else:
            return None
    except KeyError:
        return None
    return series.dropna() if isinstance(series, pd.Series) else None


# Ceiling on one batched download. The API route answers empty after
# WORLDFIN_UPSTREAM_TIMEOUT_S, but a socket that never returns keeps a thread alive, so
# the same budget is handed to yfinance as its own timeout (plan M2.3).
DEFAULT_FETCH_TIMEOUT_S = 8.0


def _fetch_timeout() -> float:
    try:
        return env_float("WORLDFIN_UPSTREAM_TIMEOUT_S", DEFAULT_FETCH_TIMEOUT_S)
    except ValueError:
        return DEFAULT_FETCH_TIMEOUT_S


# A failed download is remembered for a short while. Without this, a dead or rate-limited
# upstream is retried by every request: at 50 rps that is 50 downloads per second, each
# burning the full timeout, and the panel stays slow for as long as the outage lasts. The
# window is deliberately shorter than the quote cache, so recovery is visible quickly.
_quote_failures: dict[str, float] = {}


def _quote_fail_ttl() -> float:
    try:
        return env_float("FINSCRAPE_QUOTE_FAIL_TTL", 30.0)
    except ValueError:
        return 30.0


def _recently_failed(symbols: list[str], now: float) -> set[str]:
    return {s for s in symbols if _quote_failures.get(s, 0.0) > now}


def _record_failure(symbols: list[str], now: float) -> None:
    until = now + _quote_fail_ttl()
    for symbol in symbols:
        _quote_failures[symbol] = until


def _fetch_quotes(symbols: list[str], timeout: float | None = None) -> dict[str, dict]:
    """One intraday download for the live market panel. Empty on any failure."""
    out: dict[str, dict] = {}
    if not symbols:
        return out
    try:
        df = yf.download(
            tickers=" ".join(symbols),
            period="2d",
            interval="5m",
            group_by="ticker",
            progress=False,
            threads=True,
            # yfinance annotates this as int, but the value is a requests/urllib3
            # socket timeout and accepts fractional seconds; truncating it would
            # silently shorten the configured budget (tests pin 3.5 s and 1.25 s).
            timeout=_fetch_timeout() if timeout is None else timeout,  # pyright: ignore[reportArgumentType]
        )
    except Exception as exc:
        logger.warning("Quote fetch failed: %s", exc)
        _record_failure(symbols, time.monotonic())
        return out
    if df is None or df.empty:
        _record_failure(symbols, time.monotonic())
        return out

    for symbol in symbols:
        closes = _close_series(df, symbol)
        if closes is None or len(closes) < 2:
            continue
        today = cast("pd.DatetimeIndex", closes.index)[-1].date()
        prev = cast(
            "pd.Series",
            closes[[d.date() < today for d in cast("pd.DatetimeIndex", closes.index)]],
        )
        prev_close = float(prev.iloc[-1]) if len(prev) else float(closes.iloc[0])
        price = float(closes.iloc[-1])
        if not math.isfinite(price) or not math.isfinite(prev_close) or prev_close == 0:
            continue
        out[symbol] = {
            "symbol": symbol,
            "price": round(price, 2),
            "previous_close": round(prev_close, 2),
            "change_percent": round(((price - prev_close) / prev_close) * 100, 2),
            # A compact shape for the tile; the full chart stays in /api/candles.
            "spark": [round(float(v), 2) for v in closes.iloc[-30:]],
        }
    return out


def cached_quotes(symbols: list[str]) -> list[dict]:
    """Whatever is known right now, regardless of age — never a download.

    The answer to "is a refresh already running?": a second caller gets the last snapshot
    instead of queueing behind the same upstream call and doubling the wait.
    """
    out = []
    for symbol in symbols:
        entry = _quote_cache.get(symbol)
        if entry:
            out.append(entry[0])
    return out


def get_quotes(symbols: list[str], timeout: float | None = None) -> list[dict]:
    """Intraday quotes (price, previous close, % change, 30-bar sparkline).

    Served from a 60 s per-symbol cache; only stale symbols are fetched, in one
    batched call. Returns symbols that resolved, in request order. `timeout` is the
    per-download ceiling the caller is willing to wait for.
    """
    wanted = [t for t in dict.fromkeys(symbols) if isinstance(t, str) and t]
    if not wanted:
        return []

    now = time.monotonic()
    ttl = _quote_ttl()
    fresh: dict[str, dict] = {}
    stale: list[str] = []
    recently_failed = _recently_failed(wanted, now)
    for symbol in wanted:
        entry = _quote_cache.get(symbol)
        if entry and (now - entry[1]) < ttl:
            fresh[symbol] = entry[0]
        elif symbol in recently_failed:
            # Answered from the failure window: no download, no wait, same empty tile.
            continue
        else:
            stale.append(symbol)

    if stale:
        for symbol, quote in _fetch_quotes(stale, timeout).items():
            _quote_cache[symbol] = (quote, now)
            fresh[symbol] = quote

    return [fresh[s] for s in wanted if s in fresh]


def _reaction_ttl() -> float:
    try:
        return env_float("FINSCRAPE_REACTION_TTL", 300.0)
    except ValueError:
        return 300.0


def _fetch_market_reaction(symbols: list[str]) -> dict[str, dict]:
    """One batched 3-month daily download → one-day move, volume spike and flow proxy.

    Volume is compared with the prior 20 sessions (excluding today) so the event
    day itself does not raise the baseline it is measured against. A close near
    the day's high gives a positive Chaikin-style flow multiplier; near the low,
    negative. This is evidence, not a separate directional call.
    """
    out: dict[str, dict] = {}
    if not symbols:
        return out
    try:
        df = yf.download(
            tickers=" ".join(symbols),
            period="3mo",
            interval="1d",
            group_by="ticker",
            progress=False,
            auto_adjust=False,
            threads=True,
        )
    except Exception as exc:
        logger.warning("Market reaction fetch failed: %s", exc)
        return out
    if df is None or df.empty:
        return out

    for symbol in symbols:
        try:
            frame = (
                _symbol_frame(df, symbol)
                if isinstance(df.columns, pd.MultiIndex)
                else df
            )
            close = _column(frame, "Close").dropna()
            if len(close) < 2:
                continue
            volume = _column(frame, "Volume").reindex(close.index).fillna(0.0)
            high = _column(frame, "High").reindex(close.index)
            low = _column(frame, "Low").reindex(close.index)
            price = float(close.iloc[-1])
            prev = float(close.iloc[-2])
            last_volume = float(volume.iloc[-1])
            prior_volume = volume.iloc[-21:-1]
            avg_volume = (
                float(prior_volume.mean())
                if len(prior_volume)
                else float(volume.iloc[:-1].mean())
            )
            if not math.isfinite(price) or not math.isfinite(prev) or prev == 0:
                continue
            if not math.isfinite(avg_volume) or avg_volume <= 0:
                avg_volume = 0.0
            last_high = (
                float(high.iloc[-1]) if math.isfinite(float(high.iloc[-1])) else price
            )
            last_low = (
                float(low.iloc[-1]) if math.isfinite(float(low.iloc[-1])) else price
            )
            span = last_high - last_low
            clv = ((price - last_low) - (last_high - price)) / span if span > 0 else 0.0
            prior_clv = []
            prior_dollar = []
            for i in range(max(0, len(close) - 21), len(close) - 1):
                hi_i = float(high.iloc[i])
                lo_i = float(low.iloc[i])
                span_i = hi_i - lo_i
                clv_i = (
                    ((float(close.iloc[i]) - lo_i) - (hi_i - float(close.iloc[i])))
                    / span_i
                    if span_i > 0
                    else 0.0
                )
                prior_clv.append(clv_i * float(volume.iloc[i]))
                prior_dollar.append(float(close.iloc[i]) * float(volume.iloc[i]))
            avg_flow = sum(prior_clv) / len(prior_clv) if prior_clv else 0.0
            last_flow = clv * last_volume
            dollar_volume = price * last_volume
            avg_dollar = sum(prior_dollar) / len(prior_dollar) if prior_dollar else 0.0
            out[symbol] = {
                "ticker": symbol,
                "price": round(price, 2),
                "previous_close": round(prev, 2),
                "change_percent": round(((price - prev) / prev) * 100, 2),
                "volume": round(last_volume, 0),
                "avg_volume_20d": round(avg_volume, 0),
                "volume_ratio": round(last_volume / avg_volume, 2)
                if avg_volume
                else 0.0,
                "dollar_volume": round(dollar_volume, 0),
                "avg_dollar_volume_20d": round(avg_dollar, 0),
                "dollar_volume_ratio": round(dollar_volume / avg_dollar, 2)
                if avg_dollar
                else 0.0,
                "money_flow_ratio": round(last_flow / avg_flow, 2) if avg_flow else 0.0,
                "range_percent": round((span / prev) * 100, 2),
            }
        except Exception as exc:
            logger.debug("Market reaction skip %s: %s", symbol, exc)
            continue
    return out


def get_market_reaction(symbols: list[str]) -> dict[str, dict]:
    """One-day price move plus volume/dollar-volume/flow ratios, TTL-cached.

    Returns `{ticker: metrics}` for symbols that resolved. Missing data is simply
    absent; callers must treat that as "no confirmation", not as neutral evidence.
    """
    wanted = [t for t in dict.fromkeys(symbols) if isinstance(t, str) and t]
    if not wanted:
        return {}

    now = time.monotonic()
    ttl = _reaction_ttl()
    fresh: dict[str, dict] = {}
    stale: list[str] = []
    for symbol in wanted:
        entry = _reaction_cache.get(symbol)
        if entry and (now - entry[1]) < ttl:
            fresh[symbol] = entry[0]
        else:
            stale.append(symbol)

    if stale:
        for symbol, reaction in _fetch_market_reaction(stale).items():
            _reaction_cache[symbol] = (reaction, now)
            fresh[symbol] = reaction

    return {symbol: fresh[symbol] for symbol in wanted if symbol in fresh}


MIN_INDICATOR_BARS = 50  # sma50 is the binding constraint


def _rsi14(closes: list[float], period: int = 14) -> float:
    """Standard RSI over the last `period` closes. All-gains -> 100.0,
    no-change (flat) series -> 50.0 (neutral, not undefined)."""
    deltas = [
        closes[i] - closes[i - 1] for i in range(len(closes) - period, len(closes))
    ]
    avg_gain = sum(d for d in deltas if d > 0) / period
    avg_loss = sum(-d for d in deltas if d < 0) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _atr_pct(
    closes: list[float], highs: list[float], lows: list[float], period: int = 14
) -> float:
    """Average True Range over the last `period` bars, as a % of the latest close."""
    trs = []
    for i in range(len(closes) - period, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    atr = sum(trs) / period
    return round(atr / closes[-1] * 100, 2) if closes[-1] else 0.0


def compute_indicators(
    closes: list[float], highs: list[float], lows: list[float]
) -> dict:
    """Pure technical indicators over plain price lists — no TA-Lib, no pandas here,
    so this is testable offline with synthetic data.

    Needs at least MIN_INDICATOR_BARS closes (sma50 is the longest window); returns {}
    on short or mismatched-length input rather than crash or emit partial/misleading facts.
    """
    n = len(closes)
    if n < MIN_INDICATOR_BARS or len(highs) != n or len(lows) != n:
        return {}

    sma20 = sum(closes[-20:]) / 20
    sma50 = sum(closes[-50:]) / 50
    high_water = max(closes)

    return {
        "rsi14": _rsi14(closes),
        "sma20": round(sma20, 2),
        "sma50": round(sma50, 2),
        "atr_pct": _atr_pct(closes, highs, lows),
        "ret_5d": round((closes[-1] - closes[-6]) / closes[-6] * 100, 2),
        "pct_from_52w_high": round((closes[-1] - high_water) / high_water * 100, 2),
    }


def _fetch_indicators(tickers: list[str]) -> dict[str, dict]:
    """One batched 1y yfinance call for `tickers` → {ticker: indicator_dict}. Degrades
    to {} on any error, same as `_fetch`, so a dead yfinance never crashes the council.

    Needs the full 1y so `pct_from_52w_high` covers an actual 52 weeks, not a 6mo window
    wearing a 52-week label."""
    out: dict[str, dict] = {}
    try:
        df = yf.download(
            tickers=" ".join(tickers), period="1y", interval="1d", progress=False
        )
        if df is None or df.empty or "Close" not in df.columns:
            return out
        for t in tickers:
            try:
                if len(tickers) > 1:
                    close = _column(_symbol_frame(df, "Close"), t)
                    high = _column(_symbol_frame(df, "High"), t)
                    low = _column(_symbol_frame(df, "Low"), t)
                else:
                    close = _column(df, "Close")
                    high = _column(df, "High")
                    low = _column(df, "Low")
                sub = pd.concat({"c": close, "h": high, "l": low}, axis=1).dropna()
                indicators = compute_indicators(
                    sub["c"].astype(float).tolist(),
                    sub["h"].astype(float).tolist(),
                    sub["l"].astype(float).tolist(),
                )
                if indicators:
                    out[t] = indicators
            except Exception:
                continue
    except Exception as e:
        logger.warning("Indicator fetch error: %s", e)
    return out


def get_indicators(tickers: list[str]) -> dict[str, dict]:
    """Fetch RSI/SMA/ATR/return/52w-high indicators per ticker, served from a TTL
    cache, one batched yfinance call for the tickers whose entry is missing/stale."""
    tickers = [t for t in tickers if isinstance(t, str) and t]
    if not tickers:
        return {}

    now = time.monotonic()
    ttl = _ttl()
    fresh: dict[str, dict] = {}
    stale: list[str] = []
    for t in dict.fromkeys(tickers):
        entry = _indicator_cache.get(t)
        if entry and (now - entry[1]) < ttl:
            fresh[t] = entry[0]
        else:
            stale.append(t)

    if stale:
        fetched = _fetch_indicators(stale)
        for t, result in fetched.items():
            _indicator_cache[t] = (result, now)
            fresh[t] = result

    return {t: fresh[t] for t in dict.fromkeys(tickers) if t in fresh}


def window_move(closes: pd.Series, at: dt.datetime, hours_after: float) -> float | None:
    """% move from the last close before the event's day to the Nth trading-day close
    after it (N = days in `hours_after`, min 1). None until that close exists."""
    closes = closes.dropna()
    day = _event_day(at)
    n = max(1, math.ceil(hours_after / 24))
    before = cast("pd.Series", closes[closes.index < day])
    after = cast("pd.Series", closes[closes.index > day])
    if before.empty or len(after) < n or before.iloc[-1] == 0:
        return None
    return float((after.iloc[n - 1] - before.iloc[-1]) / before.iloc[-1] * 100)


def _event_day(at: dt.datetime) -> pd.Timestamp:
    ts = pd.Timestamp(at)
    if ts.tzinfo:
        ts = cast("pd.Timestamp", ts.tz_convert("UTC")).tz_localize(None)
    return cast("pd.Timestamp", ts).normalize()


def event_move(tickers: list[str], at: dt.datetime, hours_after: float) -> float | None:
    """Mean `window_move` across `tickers`."""
    moves = event_moves(tickers, at, hours_after)
    return sum(moves.values()) / len(moves) if moves else None


def event_moves(
    tickers: list[str], at: dt.datetime, hours_after: float
) -> dict[str, float]:
    """`window_move` per ticker from one yfinance download around `at`."""
    tickers = [t for t in dict.fromkeys(tickers) if isinstance(t, str) and t]
    if not tickers:
        return {}
    day = _event_day(at)
    try:
        df = yf.download(
            tickers=tickers,
            start=(day - pd.Timedelta(days=7)).date().isoformat(),
            end=(day + pd.Timedelta(hours=hours_after, days=6)).date().isoformat(),
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
    except Exception as e:
        logger.warning("Window fetch error: %s", e)
        return {}
    if df is None or df.empty or "Close" not in df.columns:
        return {}
    close = df["Close"]
    series: dict[str, pd.Series] = {}
    if isinstance(close, pd.Series):
        series[tickers[0]] = close
    else:
        close_frame = cast("pd.DataFrame", close)
        series = {str(t): _column(close_frame, t) for t in close_frame.columns}
    moves: dict[str, float] = {}
    for sym, s in series.items():
        s.index = cast("pd.DatetimeIndex", pd.to_datetime(s.index)).tz_localize(None)
        move = window_move(s, at, hours_after)
        if move is not None:
            moves[str(sym)] = move
    return moves


EXCESS_HORIZONS = (2, 4)


def excess_moves(
    closes: pd.DataFrame, at: dt.datetime, opens: pd.DataFrame | None = None
) -> dict[int, dict[str, float]]:
    """% return minus SPY's, per horizon and ticker, entered at the first price a reader
    of the news could actually have traded.

    An intraday event on a trading day is entered at that day's close; news at/after the
    close, or on a closed day (weekend, holiday), is entered at the **next session's open**,
    never at the close before it — that close is a price nobody could act on, so using it
    as a base quietly banks the overnight gap the news caused (plan m1.4.2). A ticker is
    missing from a horizon until its close exists.
    """
    ts = pd.Timestamp(at)
    et = (ts if ts.tzinfo else ts.tz_localize("UTC")).tz_convert("America/New_York")
    day = cast("pd.Timestamp", et.tz_localize(None)).normalize()
    # After the close, or on a day the market is shut, the next session is the first one a
    # reader can trade. (Half-days close at 13:00 ET; 16:00 is still the safe boundary for
    # "the close has happened" because a 13:00 print is a closing print.)
    late = et.hour >= 16 or day.weekday() >= 5
    cutoff = day - pd.Timedelta(days=0 if late else 1)

    closes = closes.sort_index()
    index = cast("pd.DatetimeIndex", closes.index)
    # DatetimeIndex.searchsorted takes a Timestamp at runtime; the stubs only describe
    # the array forms, so the scalar goes in as datetime64.
    i = (
        int(
            index.searchsorted(
                cast("pd.Timestamp", cutoff).to_datetime64(), side="right"
            )
        )
        - 1
    )
    out: dict[int, dict[str, float]] = {h: {} for h in EXCESS_HORIZONS}
    if i < 0 or "SPY" not in closes:
        return out

    if late:
        base_row, shift = i + 1, 1
        if base_row >= len(closes):
            return out  # the session that could trade the news has not opened yet
        entry = None
        if opens is not None and base_row < len(opens) and "SPY" in opens:
            entry = opens.sort_index().iloc[base_row]
        if entry is None:
            # No Open bar: refuse to score rather than enter at a price that was already
            # history when the news broke. The call stays open and is counted as such.
            logger.warning(
                "no Open bar for the session after an after-close event; unscored"
            )
            return out
    else:
        entry, base_row, shift = closes.iloc[i], i, 0

    for h in EXCESS_HORIZONS:
        j = base_row + h - shift
        if j >= len(closes):
            continue
        rets = closes.iloc[j] / entry - 1
        for sym, r in rets.drop("SPY").dropna().items():
            out[h][str(sym)] = float((r - rets["SPY"]) * 100)
    return out


def event_excess(tickers: list[str], at: dt.datetime) -> dict[int, dict[str, float]]:
    """`excess_moves` from one yfinance download of `tickers` plus SPY around `at`."""
    tickers = [
        t for t in dict.fromkeys(tickers) if isinstance(t, str) and t and t != "SPY"
    ]
    empty: dict[int, dict[str, float]] = {h: {} for h in EXCESS_HORIZONS}
    if not tickers:
        return empty
    day = _event_day(at)
    try:
        df = yf.download(
            tickers=[*tickers, "SPY"],
            start=(day - pd.Timedelta(days=10)).date().isoformat(),
            end=(day + pd.Timedelta(days=14)).date().isoformat(),
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
    except Exception as e:
        logger.warning("Excess fetch error: %s", e)
        return empty
    if df is None or df.empty or "Close" not in df.columns:
        return empty
    close = df["Close"]
    close_frame = cast("pd.DataFrame", close)
    # SPY's calendar is the trading calendar; crypto's weekend closes would shift it.
    close_frame = close_frame[_column(close_frame, "SPY").notna()]
    close_frame.index = cast(
        "pd.DatetimeIndex", pd.to_datetime(close_frame.index)
    ).tz_localize(None)
    # After-close news is entered at the next session's open, so the open has to come along.
    open_frame = close_frame
    if "Open" in df.columns:
        opens = cast("pd.DataFrame", df["Open"])
        opens = opens.reindex(close_frame.index)
        opens.index = close_frame.index
        open_frame = opens
    # Today's bar is intraday until the close, so it is never a horizon's close.
    today = cast(
        "pd.Timestamp", pd.Timestamp.now("America/New_York").normalize()
    ).tz_localize(None)
    keep = close_frame.index < today
    return excess_moves(
        cast("pd.DataFrame", close_frame[keep]),
        at,
        cast("pd.DataFrame", open_frame[keep]),
    )
