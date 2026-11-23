"""Keyless free-API ingestors for world signals.

Each ingestor pulls a public, no-auth API and emits `RawGeoEvent`s that flow into the
same analyze→judge pipeline as scraped articles (worker, Phase 3). Network `fetch_raw`
is kept separate from the pure `parse` so the parsers are unit-tested against fixtures
with no network. Endpoints are public facts (verified present in worldmonitor), not
copied source.

Crypto was removed from the event mix (CoinGeckoIngestor stays in coingecko.py for
reference but is not registered) — FinScrape covers equities/geopolitics.
"""

from finscrape.fetchers.ingestors.base import BaseIngestor, RawGeoEvent
from finscrape.fetchers.ingestors.coingecko import CoinGeckoIngestor
from finscrape.fetchers.ingestors.gdelt import GDELTIngestor
from finscrape.fetchers.ingestors.opensky import OpenSkyIngestor
from finscrape.fetchers.ingestors.reliefweb import ReliefWebIngestor
from finscrape.fetchers.ingestors.usgs import USGSQuakesIngestor

# Event-producing ingestors (OpenSky is a flights data layer, not an event source;
# CoinGecko was de-registered when the crypto section was removed).
EVENT_INGESTORS = (
    USGSQuakesIngestor,
    GDELTIngestor,
    ReliefWebIngestor,
)

__all__ = [
    "EVENT_INGESTORS",
    "BaseIngestor",
    "CoinGeckoIngestor",
    "GDELTIngestor",
    "OpenSkyIngestor",
    "RawGeoEvent",
    "ReliefWebIngestor",
    "USGSQuakesIngestor",
]
