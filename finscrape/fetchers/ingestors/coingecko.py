"""CoinGecko market movers — keyless JSON. Emits an event only for notable 24h moves
so the pipeline doesn't drown in noise; full coin table feeds the CryptoPanel (Phase 6).
"""

from __future__ import annotations

from typing import Any

from finscrape.fetchers.ingestors.base import BaseIngestor, RawGeoEvent

_MOVE_THRESHOLD = 8.0  # |24h %| to count as a notable move


class CoinGeckoIngestor(BaseIngestor):
    name = "coingecko"
    base_url = "https://api.coingecko.com/api/v3/coins/markets"

    def __init__(self, threshold: float = _MOVE_THRESHOLD, per_page: int = 50):
        self.threshold = threshold
        self.per_page = per_page

    def fetch_raw(self, url: str | None = None, params: dict | None = None) -> Any:
        return super().fetch_raw(
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": self.per_page,
                "page": 1,
                "price_change_percentage": "24h",
            }
        )

    def parse(self, data: Any) -> list[RawGeoEvent]:
        events: list[RawGeoEvent] = []
        for coin in data or []:
            pct = coin.get("price_change_percentage_24h")
            symbol = (coin.get("symbol") or "").upper()
            name = coin.get("name") or symbol
            if pct is None or symbol == "" or abs(pct) < self.threshold:
                continue
            direction = "surged" if pct > 0 else "dropped"
            events.append(
                RawGeoEvent(
                    title=f"{name} ({symbol}) {direction} {pct:+.1f}% in 24h",
                    text=f"{name} {direction} {pct:+.1f}% over 24h to ${coin.get('current_price')}.",
                    source="coingecko:market",
                    event_type="market_movement",
                    tickers=[symbol],
                )
            )
        return events
