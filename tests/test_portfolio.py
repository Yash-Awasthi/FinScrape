"""Tests for the portfolio position shape."""

from finscrape.portfolio import Position


class TestPositionDataclass:
    def test_to_dict(self):
        pos = Position(ticker="AAPL", shares=100, avg_cost=150.0, current_price=175.0)
        d = pos.to_dict()
        assert d["ticker"] == "AAPL"
        assert d["market_value"] == 17500.0
        assert d["unrealized_pnl"] == 2500.0

    def test_from_dict(self):
        d = {"ticker": "AAPL", "shares": 100, "avg_cost": 150.0, "current_price": 175.0}
        pos = Position.from_dict(d)
        assert pos.ticker == "AAPL"
        assert pos.shares == 100
