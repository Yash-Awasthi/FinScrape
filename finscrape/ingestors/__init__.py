"""Back-compat shim: ingestors moved to `finscrape/fetchers/ingestors/` (plan M3.4)."""

from finscrape.fetchers.ingestors import *  # noqa: F403
from finscrape.fetchers.ingestors import (  # noqa: F401
    EVENT_INGESTORS,
    BaseIngestor,
    CoinGeckoIngestor,
    GDELTIngestor,
    OpenSkyIngestor,
    RawGeoEvent,
    ReliefWebIngestor,
    USGSQuakesIngestor,
)
