"""USGS earthquakes (M4.5+, past week). Keyless GeoJSON. Carries exact lat/lon."""

from __future__ import annotations

import datetime as _dt
from typing import Any

from finscrape.ingestors.base import BaseIngestor, RawGeoEvent

_MIN_MAG = 4.5


class USGSQuakesIngestor(BaseIngestor):
    name = "usgs_quakes"
    base_url = (
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson"
    )

    def parse(self, data: Any) -> list[RawGeoEvent]:
        events: list[RawGeoEvent] = []
        for feat in (data or {}).get("features", []):
            props = feat.get("properties") or {}
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates") or []
            mag = props.get("mag")
            place = props.get("place") or "unknown location"
            if mag is None or mag < _MIN_MAG or len(coords) < 2:
                continue
            lon, lat = coords[0], coords[1]
            ts = props.get("time")
            published = (
                _dt.datetime.fromtimestamp(ts / 1000, tz=_dt.UTC).isoformat()
                if isinstance(ts, (int, float))
                else None
            )
            events.append(
                RawGeoEvent(
                    title=f"M{mag} earthquake — {place}",
                    text=f"A magnitude {mag} earthquake struck {place}.",
                    source="usgs_quakes:gov",
                    event_type="other",
                    lat=lat,
                    lon=lon,
                    published_at=published,
                    url=props.get("url", ""),
                )
            )
        return events
