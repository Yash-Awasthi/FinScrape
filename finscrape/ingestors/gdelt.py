"""GDELT 2.0 events export — the 15-minute file, not the rate-limited DOC API.

The DOC API answered 429 to most requests at any interval; the export is a static
zip published every 15 minutes. It carries no titles, so the source URL's slug
stands in, and it adds what the DOC API lacked: CAMEO codes, mention counts, geo.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from typing import Any
from urllib.parse import urlparse

import requests

from finscrape.entity_map import resolve_company_tickers, resolve_tickers
from finscrape.ingestors.base import _HEADERS, _TIMEOUT, BaseIngestor, RawGeoEvent

logger = logging.getLogger(__name__)

LASTUPDATE = "https://data.gdeltproject.org/gdeltv2/lastupdate.txt"

# Events table columns (GDELT 2.0 codebook). QuadClass 3/4 = verbal/material conflict.
_QUAD, _MENTIONS = 29, 31
_LAT, _LON, _ADDED, _URL = 56, 57, 59, 60


def slug_title(url: str) -> str:
    """A readable headline from the URL path, or "" when no segment reads as words."""
    for seg in reversed(urlparse(url).path.split("/")):
        seg = re.sub(r"\.\w{2,5}$", "", seg)
        words = [w for w in re.split(r"[-_+]+", seg) if w and not re.search(r"\d", w)]
        if len(words) >= 4 and sum(w.isalpha() for w in words) >= 3:
            title = " ".join(words)
            return title[0].upper() + title[1:]
    return ""


def _float(v: str) -> float | None:
    try:
        return float(v)
    except ValueError:
        return None


class GDELTIngestor(BaseIngestor):
    name = "gdelt"
    base_url = LASTUPDATE

    def __init__(self, max_records: int = 30):
        self.max_records = max_records

    def fetch_raw(self, url: str | None = None, params: dict | None = None) -> Any:
        """The newest events export as zip bytes, or None."""
        try:
            listing = requests.get(LASTUPDATE, headers=_HEADERS, timeout=_TIMEOUT)
            listing.raise_for_status()
            export = next(
                line.split()[-1]
                for line in listing.text.splitlines()
                if line.endswith(".export.CSV.zip")
            )
            resp = requests.get(
                export.replace("http://", "https://"),
                headers=_HEADERS,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.content
        except (requests.RequestException, StopIteration) as exc:
            logger.warning("[ingestor/gdelt] export fetch failed: %s", exc)
            return None

    def parse(self, data: Any) -> list[RawGeoEvent]:
        if not data:
            return []
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            text = zf.read(zf.namelist()[0]).decode("utf-8", errors="replace")
        best: dict[str, list[str]] = {}
        for row in csv.reader(io.StringIO(text), delimiter="\t"):
            if len(row) <= _URL or row[_QUAD] not in ("3", "4"):
                continue
            url = row[_URL]
            if url not in best or int(row[_MENTIONS] or 0) > int(
                best[url][_MENTIONS] or 0
            ):
                best[url] = row
        events: list[RawGeoEvent] = []
        # Material conflict (force, blockades) before verbal, then by coverage.
        ranked = sorted(
            best.items(),
            key=lambda kv: (kv[1][_QUAD] != "4", -int(kv[1][_MENTIONS] or 0)),
        )
        for url, row in ranked:
            title = slug_title(url)
            # Stand-in for the DOC API's topic query: most conflict rows are local
            # crime, and a title that implies no ticker never survives the pipeline.
            if not title or not (
                resolve_tickers(title) or resolve_company_tickers(title)
            ):
                continue
            events.append(
                RawGeoEvent(
                    title=title,
                    text=title,
                    source=f"gdelt/{urlparse(url).netloc.removeprefix('www.')}:wire",
                    event_type="geopolitical_event",
                    lat=_float(row[_LAT]),
                    lon=_float(row[_LON]),
                    published_at=row[_ADDED],
                    url=url,
                )
            )
            if len(events) >= self.max_records:
                break
        return events
