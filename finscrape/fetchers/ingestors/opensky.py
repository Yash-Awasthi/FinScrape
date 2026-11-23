"""OpenSky live aircraft states — keyless JSON.

This is a DATA-LAYER ingestor (a future flights panel / globe layer), not an event
source — aircraft positions aren't market signals, so it returns structured states
rather than RawGeoEvents. `parse` satisfies the base contract by returning [].
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from finscrape.fetchers.ingestors.base import BaseIngestor, RawGeoEvent


@dataclass
class AircraftState:
    icao24: str
    callsign: str
    origin_country: str
    lon: float | None
    lat: float | None
    altitude_m: float | None
    on_ground: bool


class OpenSkyIngestor(BaseIngestor):
    name = "opensky"
    base_url = "https://opensky-network.org/api/states/all"

    def parse(self, data: Any) -> list[RawGeoEvent]:
        # Not an event source — see module docstring.
        return []

    def parse_states(self, data: Any) -> list[AircraftState]:
        """State vector layout per the OpenSky REST API (positional array)."""
        out: list[AircraftState] = []
        for s in (data or {}).get("states") or []:
            if len(s) < 9:
                continue
            out.append(
                AircraftState(
                    icao24=s[0],
                    callsign=(s[1] or "").strip(),
                    origin_country=s[2],
                    lon=s[5],
                    lat=s[6],
                    altitude_m=s[7],
                    on_ground=bool(s[8]),
                )
            )
        return out

    def fetch_states(self) -> list[AircraftState]:
        data = self.fetch_raw()
        return self.parse_states(data) if data is not None else []
