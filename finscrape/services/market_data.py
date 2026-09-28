"""
Market Data Service — Inspired by yfinance and Yahoo Finance data patterns.

Provides market data retrieval, caching, and normalization. Supports
stocks, ETFs, indices, and crypto with historical and real-time data.
All pure functions for data transformation — fetching is pluggable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MarketQuote:
    """Real-time or delayed market quote."""
    symbol: str
    name: str
    price: float
    change: float
    change_pct: float
    volume: int
    market_cap: float
    pe_ratio: Optional[float] = None
    dividend_yield: Optional[float] = None
    fifty_two_week_high: float = 0
    fifty_two_week_low: float = 0
    timestamp: str = ""


@dataclass
class HistoricalBar:
    """Historical OHLCV bar."""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    adjusted_close: float
    dividend: float = 0
    stock_split: float = 1.0


@dataclass
class MarketSnapshot:
    """Aggregated market snapshot for multiple symbols."""
    symbols: List[str]
    timestamp: str
    quotes: Dict[str, MarketQuote]
    sector_performance: Dict[str, float]
    market_status: str  # "open", "closed", "pre-market", "after-hours"


@dataclass
class DataQuality:
    """Data quality metrics for a symbol's historical data."""
    symbol: str
    total_bars: int
    missing_bars: int
    date_range: Tuple[str, str]
    completeness: float  # 0.0 to 1.0
    has_splits: bool
    has_dividends: bool
    volume_anomalies: int  # bars with volume = 0


# ---------------------------------------------------------------------------
# Data normalization
# ---------------------------------------------------------------------------

def normalize_symbol(raw_symbol: str) -> str:
    """
    Normalize a symbol to standard format.
    
    Handles various input formats:
    - "aapl" → "AAPL"
    - "BRK.B" → "BRK-B" (Yahoo format)
    - "BTC-USD" → "BTC-USD" (crypto)
    - "000001.SS" → "000001.SS" (Shanghai)
    """
    symbol = raw_symbol.strip().upper()
    
    # Handle dot separators (European format)
    if '.' in symbol and not symbol.endswith('.USD'):
        parts = symbol.split('.')
        if len(parts) == 2 and len(parts[1]) == 2:
            symbol = f"{parts[0]}-{parts[1]}"
    
    return symbol


def parse_historical_data(
    raw_data: List[Dict],
    symbol: str,
) -> List[HistoricalBar]:
    """
    Parse raw historical data into normalized HistoricalBar objects.
    
    Handles various input formats from different data providers.
    """
    bars = []
    for row in raw_data:
        try:
            bar = HistoricalBar(
                date=str(row.get("Date", row.get("date", ""))),
                open=float(row.get("Open", row.get("open", 0))),
                high=float(row.get("High", row.get("high", 0))),
                low=float(row.get("Low", row.get("low", 0))),
                close=float(row.get("Close", row.get("close", 0))),
                volume=int(row.get("Volume", row.get("volume", 0))),
                adjusted_close=float(row.get("Adj Close", row.get("adj_close", row.get("close", 0)))),
                dividend=float(row.get("Dividends", row.get("dividend", 0))),
                stock_split=float(row.get("Stock Splits", row.get("stock_split", 1))),
            )
            bars.append(bar)
        except (ValueError, KeyError):
            continue
    
    return bars


def adjust_for_splits(
    bars: List[HistoricalBar],
) -> List[HistoricalBar]:
    """
    Adjust historical prices for stock splits.
    
    Backward-adjusts all prices before each split event.
    """
    if not bars:
        return []
    
    adjusted = []
    cumulative_adjustment = 1.0
    
    # Process from oldest to newest
    for bar in reversed(bars):
        if bar.stock_split != 1.0:
            cumulative_adjustment *= bar.stock_split
        
        adjusted_bar = HistoricalBar(
            date=bar.date,
            open=bar.open / cumulative_adjustment,
            high=bar.high / cumulative_adjustment,
            low=bar.low / cumulative_adjustment,
            close=bar.close / cumulative_adjustment,
            volume=int(bar.volume * cumulative_adjustment),
            adjusted_close=bar.adjusted_close,
            dividend=bar.dividend,
            stock_split=bar.stock_split,
        )
        adjusted.append(adjusted_bar)
    
    adjusted.reverse()
    return adjusted


def calculate_returns(
    bars: List[HistoricalBar],
    period: str = "daily",
) -> List[float]:
    """
    Calculate returns from historical bars.
    
    Args:
        bars: Historical bars in chronological order
        period: "daily", "weekly", "monthly"
    
    Returns:
        List of returns (not percentage)
    """
    if len(bars) < 2:
        return []
    
    closes = [b.adjusted_close for b in bars]
    returns = []
    
    for i in range(1, len(closes)):
        if closes[i - 1] != 0:
            returns.append((closes[i] - closes[i - 1]) / closes[i - 1])
        else:
            returns.append(0.0)
    
    return returns


# ---------------------------------------------------------------------------
# Data quality analysis
# ---------------------------------------------------------------------------

def assess_data_quality(bars: List[HistoricalBar], symbol: str = "") -> DataQuality:
    """
    Assess the quality of historical data.
    
    Checks for:
    - Missing bars (gaps in date sequence)
    - Volume anomalies (zero volume)
    - Stock splits and dividends
    - Date range completeness
    """
    if not bars:
        return DataQuality(
            symbol=symbol, total_bars=0, missing_bars=0,
            date_range=("", ""), completeness=0,
            has_splits=False, has_dividends=False, volume_anomalies=0,
        )
    
    total = len(bars)
    volume_anomalies = sum(1 for b in bars if b.volume == 0)
    has_splits = any(b.stock_split != 1.0 for b in bars)
    has_dividends = any(b.dividend > 0 for b in bars)
    
    # Estimate missing bars (assume daily data, check for gaps > 5 calendar days)
    missing = 0
    for i in range(1, len(bars)):
        try:
            d1 = datetime.strptime(bars[i - 1].date[:10], "%Y-%m-%d")
            d2 = datetime.strptime(bars[i].date[:10], "%Y-%m-%d")
            gap_days = (d2 - d1).days
            if gap_days > 5:  # More than a business week
                missing += gap_days - 1  # Approximate missing bars
        except (ValueError, IndexError):
            continue
    
    completeness = max(0, 1 - missing / max(1, total + missing))
    
    return DataQuality(
        symbol=symbol,
        total_bars=total,
        missing_bars=missing,
        date_range=(bars[0].date, bars[-1].date),
        completeness=round(completeness, 4),
        has_splits=has_splits,
        has_dividends=has_dividends,
        volume_anomalies=volume_anomalies,
    )


# ---------------------------------------------------------------------------
# Market status
# ---------------------------------------------------------------------------

def determine_market_status(
    now: Optional[datetime] = None,
    timezone: str = "US/Eastern",
) -> str:
    """
    Determine current US market status.
    
    Returns: "open", "closed", "pre-market", "after-hours"
    """
    if now is None:
        now = datetime.now(UTC)
    
    # Simplified US market hours (UTC offsets approximate)
    hour = now.hour
    weekday = now.weekday()  # 0=Monday, 6=Sunday
    
    # Weekend
    if weekday >= 5:
        return "closed"
    
    # Pre-market: 4:00 AM - 9:30 AM ET (~9:00-14:30 UTC)
    if 9 <= hour < 14:
        return "pre-market"
    elif hour == 14 and now.minute < 30:
        return "pre-market"
    
    # Market open: 9:30 AM - 4:00 PM ET (~14:30-21:00 UTC)
    if (hour == 14 and now.minute >= 30) or (15 <= hour < 21):
        return "open"
    
    # After-hours: 4:00 PM - 8:00 PM ET (~21:00-1:00 UTC)
    if 21 <= hour or hour < 1:
        return "after-hours"
    
    return "closed"


# ---------------------------------------------------------------------------
# Sector mapping
# ---------------------------------------------------------------------------

SECTOR_MAP = {
    "Technology": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"],
    "Healthcare": ["JNJ", "UNH", "PFE", "ABBV", "MRK", "TMO", "ABT"],
    "Financial": ["JPM", "BAC", "WFC", "GS", "MS", "C", "BLK"],
    "Energy": ["XOM", "CVX", "COP", "EOG", "SLB", "PSX", "VLO"],
    "Consumer": ["PG", "KO", "PEP", "WMT", "COST", "HD", "MCD"],
    "Industrial": ["HON", "UPS", "BA", "CAT", "GE", "MMM", "DE"],
    "Communication": ["DIS", "NFLX", "CMCSA", "T", "VZ", "TMUS", "CHTR"],
}


def get_sector_for_symbol(symbol: str) -> str:
    """Look up the sector for a given symbol."""
    for sector, symbols in SECTOR_MAP.items():
        if symbol in symbols:
            return sector
    return "Unknown"


def calculate_sector_performance(
    quotes: Dict[str, MarketQuote],
) -> Dict[str, float]:
    """
    Calculate average performance by sector.
    
    Returns dict of sector_name -> average_change_pct
    """
    sector_returns: Dict[str, List[float]] = {}
    
    for symbol, quote in quotes.items():
        sector = get_sector_for_symbol(symbol)
        if sector not in sector_returns:
            sector_returns[sector] = []
        sector_returns[sector].append(quote.change_pct)
    
    return {
        sector: sum(rets) / len(rets)
        for sector, rets in sector_returns.items()
        if rets
    }


# ---------------------------------------------------------------------------
# Watchlist management
# ---------------------------------------------------------------------------

def calculate_portfolio_metrics(
    holdings: Dict[str, float],  # symbol -> shares
    quotes: Dict[str, MarketQuote],
) -> Dict[str, float]:
    """
    Calculate portfolio metrics from holdings and current quotes.
    
    Returns:
        Dict with total_value, daily_change, allocation, etc.
    """
    total_value = 0
    daily_change = 0
    
    for symbol, shares in holdings.items():
        if symbol in quotes:
            value = shares * quotes[symbol].price
            total_value += value
            daily_change += value * (quotes[symbol].change_pct / 100)
    
    # Allocation by symbol
    allocation = {}
    for symbol, shares in holdings.items():
        if symbol in quotes and total_value > 0:
            value = shares * quotes[symbol].price
            allocation[symbol] = value / total_value
    
    return {
        "total_value": round(total_value, 2),
        "daily_change": round(daily_change, 2),
        "daily_change_pct": round((daily_change / total_value * 100) if total_value > 0 else 0, 2),
        "holding_count": len(holdings),
        "allocation": allocation,
    }
