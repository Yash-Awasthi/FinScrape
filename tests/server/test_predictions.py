"""AI ticker-impacts → correlate Predictions (no DB, no network)."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("asyncpg")

from server.queries import get_recent_predictions, impact_shift


@pytest.mark.parametrize(
    ("impact", "expected"),
    [
        ({"estimated_pct": "+3-5%", "direction": "up"}, 4.0),
        ({"estimated_pct": "-8%", "direction": "down"}, -8.0),
        # the '-' in a range is a separator; only `direction` carries the sign
        ({"estimated_pct": "5-9%", "direction": "down"}, -7.0),
        ({"estimated_pct": "2%", "direction": "neutral"}, None),
        ({"estimated_pct": "N/A", "direction": "up"}, None),
        ({"direction": "up"}, None),
        ("not a dict", None),
    ],
)
def test_impact_shift(impact, expected):
    assert impact_shift(impact) == expected


class FakePool:
    def __init__(self, results):
        self._rows = [{"result": r} for r in results]

    async def fetch(self, _query, *args):
        return self._rows


def test_recent_predictions_keeps_the_strongest_call_per_ticker():
    pool = FakePool(
        [
            {
                "ticker_impacts": [
                    {"ticker": "lmt", "direction": "up", "estimated_pct": "+2%"},
                    {"ticker": "XOM", "direction": "down", "estimated_pct": "-4%"},
                ]
            },
            {
                "ticker_impacts": [
                    {"ticker": "LMT", "direction": "up", "estimated_pct": "+9%"},
                    {"ticker": "XOM", "direction": "up", "estimated_pct": "+1%"},
                    {"ticker": "", "direction": "up", "estimated_pct": "+50%"},
                    {"ticker": "KO", "direction": "neutral", "estimated_pct": "+7%"},
                ]
            },
            {},  # an analysis with no impacts at all
        ]
    )
    out = asyncio.run(get_recent_predictions(pool))
    assert out == {"LMT": 9.0, "XOM": -4.0}  # ticker uppercased, |shift| wins
