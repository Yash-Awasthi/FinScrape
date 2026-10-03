"""Analyse one event on a GitHub runner: `python -m worker.analyze_event <id>`.

The API starts this through the `analyze` workflow when its own models are all
unavailable; the stored answer is what the next click returns.
"""

from __future__ import annotations

import asyncio
import sys

from server import db
from server.settings import get_settings
from worker import key_queue
from worker.runner import store_analysis


async def main(event_id: int) -> int:
    s = get_settings()
    pool = await db.connect(s.database_url, min_size=1, max_size=2)
    try:
        await key_queue.load(pool)
        try:
            return await store_analysis(pool, [event_id])
        finally:
            await key_queue.save(pool)
    finally:
        await db.disconnect()


if __name__ == "__main__":
    stored = asyncio.run(main(int(sys.argv[1])))
    print(f"stored {stored}")
    sys.exit(0 if stored else 1)
