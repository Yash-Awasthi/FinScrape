"""Candles for the Tickers view's chart.

Network calls run in a threadpool so they never block the event loop; failures
degrade to 502, never crash.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from fastapi import APIRouter, HTTPException, Query

from finscrape.market_data import cached_quotes, get_quotes
from server.settings import get_settings

if TYPE_CHECKING:
    import pandas as pd

router = APIRouter()
logger = logging.getLogger(__name__)

# The cross-asset tape the dashboard opens with. Kept small: one batched intraday
# download, cached 60 s, and each tile is clickable through to /api/candles.
DEFAULT_QUOTE_SYMBOLS = (
    "^GSPC",
    "^IXIC",
    "^DJI",
    "^RUT",
    "^VIX",
    "^TNX",
    "CL=F",
    "GC=F",
    "BTC-USD",
    "EURUSD=X",
)
_SYMBOL_RE = re.compile(r"[A-Za-z0-9^.=-]{1,16}")
MAX_QUOTE_SYMBOLS = 20


def _parse_symbols(raw: str | None) -> list[str]:
    """Comma-separated Yahoo symbols, deduped and bounded; junk entries are dropped."""
    if not raw:
        return list(DEFAULT_QUOTE_SYMBOLS)
    out: list[str] = []
    for part in raw.split(","):
        symbol = part.strip().upper()
        if symbol and _SYMBOL_RE.fullmatch(symbol) and symbol not in out:
            out.append(symbol)
    return out[:MAX_QUOTE_SYMBOLS]


# One download at a time for the whole tape. The symbol set is fixed and small, so a second
# concurrent request has nothing to gain by starting its own yfinance call — it would only
# queue for a threadpool slot and wait the same timeout. Under load it answers from the last
# snapshot instead, which is what makes the panel fast while an upstream is slow.
_quotes_lock = asyncio.Lock()


async def _bounded_quotes(wanted: list[str], budget: float) -> list[dict]:
    """Quotes within `budget`, or [] — never an exception.

    `asyncio.wait` rather than `wait_for`: cancelling a `to_thread` call does not stop the
    thread, and `wait_for` waits for that cancellation to land, so the request would stall
    for exactly the download it was trying to escape. Here the request returns and the
    thread finishes against its own socket timeout.
    """
    if _quotes_lock.locked():
        return cached_quotes(wanted)
    async with _quotes_lock:
        return await _download_quotes(wanted, budget)


async def _download_quotes(wanted: list[str], budget: float) -> list[dict]:
    task = asyncio.create_task(asyncio.to_thread(get_quotes, wanted, budget))
    done, _pending = await asyncio.wait({task}, timeout=budget)
    if not done:
        task.cancel()
        logger.warning("quote panel timed out after %.1fs", budget)
        return []
    try:
        return task.result()
    except Exception as exc:  # noqa: BLE001 - a dead host is an empty panel, not a 500
        logger.warning("quote panel failed: %s", exc)
        return []


@router.get("/api/market/quotes")
async def quotes(symbols: str | None = Query(None, max_length=400)) -> dict:
    """Live-ish cross-asset quotes for the market tape (yfinance, threadpool).

    Bounded by `upstream_timeout_s`: a dead host answers with an empty tape instead of
    holding the request (and the panel) open. The thread cannot be killed mid-download,
    so `get_quotes` also gets the same ceiling as a socket timeout — the difference is
    that the browser stops waiting now rather than when yfinance gives up.
    """
    wanted = _parse_symbols(symbols)
    rows = await _bounded_quotes(wanted, get_settings().upstream_timeout_s)
    return {
        "quotes": rows,
        "as_of": datetime.now(UTC).isoformat(),
        "symbols": wanted,
    }


@router.get("/api/candles")
async def candles(
    # Yahoo symbols: letters, digits, and the `. ^ = -` that index/FX/futures use
    # (^GSPC, CL=F, BRK-B). Bounded so an arbitrary string never reaches yfinance.
    symbol: str = Query(
        ..., min_length=1, max_length=16, pattern=r"^[A-Za-z0-9^.=-]+$"
    ),
    period: str = Query("1mo", pattern="^(1d|5d|1mo|3mo|6mo|1y|2y)$"),
    interval: str = Query("1d", pattern="^(5m|15m|1h|1d|1wk)$"),
) -> dict:
    """OHLCV candles for the chart panel (yfinance, threadpool)."""
    try:
        import yfinance as yf

        def _fetch() -> pd.DataFrame:
            return yf.Ticker(symbol.strip().upper()).history(
                period=period, interval=interval
            )

        hist = await asyncio.to_thread(_fetch)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"candle fetch failed: {e}") from e

    if hist is None or hist.empty:
        raise HTTPException(status_code=404, detail=f"no data for {symbol}")

    # Each row is read as a plain dict: pandas' `DataFrame.__getitem__` is typed
    # as a union that may be a Series, which rejects per-cell float()/int().
    candles = [
        {
            "t": cast("pd.Timestamp", ts).isoformat(),
            "o": round(float(cells["Open"]), 4),
            "h": round(float(cells["High"]), 4),
            "l": round(float(cells["Low"]), 4),
            "c": round(float(cells["Close"]), 4),
            "v": int(cells["Volume"]),
        }
        for ts, cells in ((ts, row.to_dict()) for ts, row in hist.iterrows())
    ]
    return {"symbol": symbol.strip().upper(), "candles": candles}
