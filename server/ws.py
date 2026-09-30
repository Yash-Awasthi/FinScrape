"""WebSocket hub for the live feed.

In-process broadcast (single API replica); Redis pub/sub fan-out runs when
`get_settings().redis_enabled`. Messages: init / new_events / ai_updated / pong.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket

log = logging.getLogger("worldfin.ws")


class WSHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def add(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, message: dict) -> None:
        """Send to every client; drop any that error mid-send."""
        async with self._lock:
            targets = list(self._clients)
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            # A dead socket is dropped.
            except Exception:  # noqa: BLE001  # pragma: no cover
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)

    @property
    def count(self) -> int:
        return len(self._clients)


# Module-level singleton hub (one per API process).
hub = WSHub()
