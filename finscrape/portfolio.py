"""
Portfolio shapes — positions and watchlists as the API returns them.

Storage lives in Postgres (server.routes.portfolio).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Position:
    """A single holding in the portfolio."""

    ticker: str
    shares: float = 0.0
    avg_cost: float = 0.0
    current_price: float = 0.0
    tags: list[str] = field(default_factory=list)

    @property
    def market_value(self) -> float:
        return self.shares * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.shares * self.avg_cost

    @property
    def unrealized_pnl(self) -> float:
        if self.avg_cost == 0:
            return 0.0
        return self.market_value - self.cost_basis

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.cost_basis == 0:
            return 0.0
        return (self.unrealized_pnl / self.cost_basis) * 100

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "shares": self.shares,
            "avg_cost": self.avg_cost,
            "current_price": self.current_price,
            "tags": self.tags,
            "market_value": round(self.market_value, 2),
            "cost_basis": round(self.cost_basis, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "unrealized_pnl_pct": round(self.unrealized_pnl_pct, 2),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Position:
        return cls(
            ticker=d["ticker"],
            shares=d.get("shares", 0.0),
            avg_cost=d.get("avg_cost", 0.0),
            current_price=d.get("current_price", 0.0),
            tags=d.get("tags", []),
        )


@dataclass
class Watchlist:
    """A named group of tickers the user wants to track."""

    name: str
    tickers: list[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "tickers": self.tickers,
            "description": self.description,
        }
