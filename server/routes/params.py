"""Query-parameter validators shared by the read routes.

A malformed `?date=` used to reach `date.fromisoformat` and come back as a generic
500. Validating at the boundary answers 422 with a message that names the expected
shape, and keeps the error envelope the same as every other bad request.
"""

from __future__ import annotations

from datetime import date as _date

from fastapi import HTTPException


def day(date: str | None = None) -> str | None:
    """`?date=YYYY-MM-DD` (calendar-checked), or None when it is not supplied."""
    if date is None:
        return None
    try:
        _date.fromisoformat(date)
    except ValueError:
        raise HTTPException(
            status_code=422, detail="date must be a real calendar day as YYYY-MM-DD"
        ) from None
    return date
