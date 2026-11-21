"""ReliefWeb (UN OCHA) disasters — JSON API v2. Humanitarian/disaster signals.

v1 is decommissioned (410) and v2 rejects any appname ReliefWeb has not approved
(403), so the source only runs once RELIEFWEB_APPNAME holds an approved name:
https://apidoc.reliefweb.int/parameters#appname
"""

from __future__ import annotations

import os
from typing import Any

from finscrape.ingestors.base import BaseIngestor, RawGeoEvent


class ReliefWebIngestor(BaseIngestor):
    name = "reliefweb"
    base_url = "https://api.reliefweb.int/v2/disasters"

    @staticmethod
    def enabled() -> bool:
        return bool(os.getenv("RELIEFWEB_APPNAME"))

    def __init__(self, limit: int = 8):
        # Disasters are context, not the feed: the old 20-per-cycle limit let them
        # outnumber the news sources in the analysis budget.
        self.limit = limit

    def fetch_raw(self, url: str | None = None, params: dict | None = None) -> Any:
        # appname is required by ReliefWeb's terms; fields[] keeps the payload small.
        return super().fetch_raw(
            params={
                "appname": os.getenv("RELIEFWEB_APPNAME", ""),
                "limit": self.limit,
                "sort[]": "date:desc",
                "fields[include][]": ["name", "status", "date", "country"],
            }
        )

    def parse(self, data: Any) -> list[RawGeoEvent]:
        events: list[RawGeoEvent] = []
        for item in (data or {}).get("data", []):
            fields = item.get("fields") or {}
            name = (fields.get("name") or "").strip()
            if not name:
                continue
            countries = fields.get("country") or []
            country = countries[0].get("name") if countries else ""
            date = (fields.get("date") or {}).get("created")
            events.append(
                RawGeoEvent(
                    title=name,
                    text=f"Humanitarian disaster: {name}."
                    + (f" Country: {country}." if country else ""),
                    source="reliefweb:gov",
                    event_type="other",
                    published_at=date,
                    url=(item.get("href") or ""),
                )
            )
        return events
