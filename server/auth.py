"""API-key auth for the mutating routes (X-API-Key or Bearer)."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from server.settings import get_settings


async def require_api_key(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    """Accept `X-API-Key: <key>` or `Authorization: Bearer <key>`. 401 otherwise."""
    supplied = x_api_key
    if not supplied and authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    # Constant-time compare: a plain `!=` leaks the matching prefix length through
    # response timing. Encoded first so a non-ASCII key cannot raise out of compare.
    # Every configured key is compared, so the previous key can overlap a rotation
    # without a 401 gap (docs/KEY-ROTATION.md).
    settings = get_settings()
    supplied_bytes = supplied.encode("utf-8") if supplied else b""
    matched = False
    for key in (settings.api_key, settings.api_key_previous):
        if key:
            matched |= hmac.compare_digest(supplied_bytes, key.encode("utf-8"))
    if not supplied or not matched:
        raise HTTPException(status_code=401, detail="Unauthorized")
