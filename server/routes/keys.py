"""Embeddable widgets for the public API (plan m4.4).

One iframe-sized page per shareable thing: a scenario and the track record. The page
is HTML, not JSON, so it stays out of the OpenAPI contract (`include_in_schema=False`);
the JSON it reads stays the source of truth. The security claim is a CSP: exactly one
parent origin may frame the widget, never a wildcard.
"""

from __future__ import annotations

import hashlib
import html
import math
import secrets
import threading
import time
import uuid
from collections import deque
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from server import db
from server.auth import require_api_key

router = APIRouter()

_WIDGET_KINDS = {"scenario", "track-record"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


def _widget_origin(raw: str | None) -> str:
    """The one origin allowed to frame a widget, or raise ValueError with a reason.

    Accepts a bare `https://host[:port]` origin, plus `http://localhost[:port]` so a
    developer can embed the widget from a local page. Anything with a path, a query,
    credentials or a wildcard is refused: `frame-ancestors *` would hand every site
    the right to frame the dashboard.
    """
    if not raw:
        raise ValueError(
            "parent is required: the origin that may frame this widget, "
            "e.g. https://example.com"
        )
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https"):
        raise ValueError(
            "parent must start with https:// (or http://localhost for development)"
        )
    if not parts.netloc or parts.username or parts.password:
        raise ValueError("parent must be a bare origin, not a URL with credentials")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("parent must be a bare origin: no path, query or fragment")
    if "*" in parts.netloc:
        raise ValueError("parent must be one origin, never a wildcard")
    host = (parts.hostname or "").lower()
    if not host:
        raise ValueError("parent has no host")
    if parts.scheme == "http" and host not in _LOCAL_HOSTS:
        raise ValueError("parent: plain http is allowed only for localhost; use https")
    return f"{parts.scheme}://{parts.netloc}"


def _csp(origin: str) -> str:
    # Inline script is deliberately not allowed: the widget's own JS is served from
    # /embed/widget.js so `script-src 'self'` can stay strict.
    return (
        "default-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'; "
        f"script-src 'self'; frame-ancestors {origin}; base-uri 'none'"
    )


_WIDGET_CSS = """
:root { color-scheme: light dark; }
body { margin: 0; font: 14px/1.4 system-ui, sans-serif; background: #0d1117; color: #e6edf3; }
main { padding: 14px 16px; }
h1 { margin: 0 0 6px; font-size: 15px; font-weight: 600; }
.metric { font-size: 24px; font-weight: 700; margin: 4px 0; }
.detail { margin: 2px 0; color: #9da7b3; }
.foot { margin: 12px 16px 0; font-size: 12px; color: #9da7b3; }
a { color: #58a6ff; }
.error { color: #f85149; }
"""

_WIDGET_JS = """
(function () {
  var root = document.getElementById("fin-widget");
  if (!root) return;
  var kind = root.getAttribute("data-kind") || "";
  var id = root.getAttribute("data-id") || "";
  var url = kind === "scenario"
    ? "/api/scenarios/" + encodeURIComponent(id)
    : "/api/accuracy";
  function pct(value) { return (value * 100).toFixed(0) + "%"; }
  function fill(lines) {
    while (root.firstChild) root.removeChild(root.firstChild);
    var h = document.createElement("h1");
    h.textContent = lines.title;
    var m = document.createElement("p");
    m.className = "metric";
    m.textContent = lines.metric;
    var d = document.createElement("p");
    d.className = "detail";
    d.textContent = lines.detail;
    root.appendChild(h);
    root.appendChild(m);
    root.appendChild(d);
  }
  fetch(url, { headers: { Accept: "application/json" } })
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(function (data) {
      if (kind === "scenario") {
        var s = data.scenario || {};
        var interval = s.ci95
          ? " (95% interval " + pct(s.ci95[0]) + " to " + pct(s.ci95[1]) + ")"
          : "";
        fill({
          title: s.title || "Scenario",
          metric: typeof s.probability === "number" ? pct(s.probability) : "not scored",
          detail: (s.n_members || 0) + " member events" + interval
        });
      } else {
        fill({
          title: "Track record",
          metric: typeof data.hit_rate === "number" ? pct(data.hit_rate) : "no scored calls",
          detail: (data.n || 0) + " scored calls" + (data.ci95
            ? " (95% interval " + pct(data.ci95[0]) + " to " + pct(data.ci95[1]) + ")"
            : "")
        });
      }
    })
    .catch(function (err) {
      root.className = "error";
      root.textContent = "The widget could not load: " + err.message;
    });
})();
"""


def _widget_html(kind: str, scenario_id: str | None) -> str:
    title = "Scenario" if kind == "scenario" else "Track record"
    full_path = f"/app/scenario/{scenario_id}" if kind == "scenario" else "/#record"
    full_label = (
        "Open the full scenario" if kind == "scenario" else "Open the full track record"
    )
    data_id = html.escape(scenario_id or "", quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} - FinScrape</title>
<style>{_WIDGET_CSS}</style>
</head>
<body>
<main id="fin-widget" data-kind="{kind}" data-id="{data_id}">
<h1>{title}</h1>
<p class="detail">Loading the latest numbers...</p>
</main>
<p class="foot"><a href="{full_path}" target="_blank" rel="noopener">{full_label}</a> - not financial advice.</p>
<noscript><p class="detail">This widget needs JavaScript. <a href="{full_path}">Open the full page</a>.</p></noscript>
<script src="/embed/widget.js" defer></script>
</body>
</html>
"""


@router.get("/embed/widget.js", include_in_schema=False)
async def widget_script() -> Response:
    """The widget's one script. Served from self so `script-src 'self'` stays strict."""
    return Response(content=_WIDGET_JS, media_type="text/javascript")


@router.get("/embed/{kind}", include_in_schema=False)
async def embed_widget(
    kind: str, id: str | None = None, parent: str | None = None
) -> Response:
    """One iframe-sized widget, frameable only by the requested parent origin."""
    if kind not in _WIDGET_KINDS:
        return PlainTextResponse(f"unknown widget: {kind}", status_code=404)
    try:
        origin = _widget_origin(parent)
    except ValueError as exc:
        return PlainTextResponse(str(exc), status_code=400)
    if kind == "scenario" and not id:
        return PlainTextResponse("id is required for kind=scenario", status_code=400)
    # Never set X-Frame-Options: CSP frame-ancestors is the single source of truth, and
    # the two disagreeing is how a widget ends up silently blank.
    return HTMLResponse(
        _widget_html(kind, id), headers={"Content-Security-Policy": _csp(origin)}
    )


# --- per-consumer keys -------------------------------------------------------

KEY_PREFIX = "wfk_"
TIER_LIMITS = {"read": 60, "write": 120}
_TIERS = tuple(TIER_LIMITS)

_WINDOW_SECONDS = 60.0
_RATE: dict[str, deque[float]] = {}
_RATE_LOCK = threading.Lock()


def hash_key(raw: str) -> str:
    """The only form stored: sha256 hex. A leaked table cannot be replayed."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_key(label: str, tier: str = "read") -> tuple[str, dict[str, Any]]:
    """Mint a key. The caller gets the plaintext exactly once; the row keeps the hash."""
    if tier not in _TIERS:
        raise ValueError(f"tier must be one of {', '.join(_TIERS)}")
    cleaned = label.strip()
    if not cleaned or len(cleaned) > 80:
        raise ValueError("label must be 1-80 characters")
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    row = {
        "id": uuid.uuid4().hex,
        "label": cleaned,
        "tier": tier,
        "key_hash": hash_key(raw),
        "key_prefix": raw[:12],
    }
    return raw, row


def rate_limit(tier: str) -> int:
    """Requests allowed per rolling minute for a tier. Unknown tiers read like `read`."""
    return TIER_LIMITS.get(tier, TIER_LIMITS["read"])


def _over_limit(key_id: str, tier: str, *, now: float | None = None) -> float | None:
    """None when the call fits the sliding window, else seconds until a slot frees."""
    at = time.monotonic() if now is None else now
    ceiling = rate_limit(tier)
    with _RATE_LOCK:
        hits = _RATE.setdefault(key_id, deque())
        while hits and at - hits[0] >= _WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= ceiling:
            return max(0.0, _WINDOW_SECONDS - (at - hits[0]))
        hits.append(at)
        return None


def reset_rate_limits() -> None:
    """Tests and the admin key list both need a clean window; nothing else calls this."""
    with _RATE_LOCK:
        _RATE.clear()


async def authenticate_consumer(raw: str) -> dict[str, Any] | None:
    """The row for a live key, or None for unknown/revoked. Touches last_used_at."""
    row = await db.pool().fetchrow(
        "UPDATE consumer_keys SET last_used_at = now() "
        "WHERE key_hash = $1 AND revoked_at IS NULL "
        "RETURNING id, label, tier, key_prefix",
        hash_key(raw),
    )
    return dict(row) if row else None


def _bearer(x_api_key: str | None, authorization: str | None) -> str | None:
    if x_api_key:
        return x_api_key
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def require_consumer(tier: str = "read"):
    """Dependency factory: 401 unknown/revoked, 403 under-tiered, 429 over the window.

    `Retry-After` is seconds, so a client backs off for exactly as long as it must.
    """

    async def dependency(
        x_api_key: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        raw = _bearer(x_api_key, authorization)
        if not raw:
            raise HTTPException(status_code=401, detail="consumer key required")
        consumer = await authenticate_consumer(raw)
        if consumer is None:
            raise HTTPException(status_code=401, detail="unknown or revoked key")
        if tier == "write" and consumer["tier"] != "write":
            raise HTTPException(status_code=403, detail="this key is read-only")
        wait = _over_limit(str(consumer["id"]), str(consumer["tier"]))
        if wait is not None:
            raise HTTPException(
                status_code=429,
                detail="rate limit exceeded",
                headers={"Retry-After": str(max(1, math.ceil(wait)))},
            )
        return consumer

    return dependency


_KEY_COLUMNS = "id, label, tier, key_prefix, created_at, last_used_at, revoked_at"


def _public(row: Any) -> dict[str, Any]:
    """Project a stored row onto what a caller may see. No hash leaves this process."""
    data = dict(row)
    return {name: data.get(name) for name in _KEY_COLUMNS.split(", ")}


@router.post("/api/admin/keys", dependencies=[Depends(require_api_key)])
async def create_consumer_key(payload: dict = Body(...)) -> dict:
    """Body: {label, tier?: read|write}. The response is the only time the key is shown."""
    try:
        raw, row = issue_key(
            str(payload.get("label") or ""), str(payload.get("tier") or "read")
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    stored = await db.pool().fetchrow(
        "INSERT INTO consumer_keys (id, label, tier, key_hash, key_prefix) "
        "VALUES ($1, $2, $3, $4, $5) RETURNING " + _KEY_COLUMNS,
        row["id"],
        row["label"],
        row["tier"],
        row["key_hash"],
        row["key_prefix"],
    )
    return {"ok": True, "key": raw, "consumer": _public(stored or row)}


@router.get("/api/admin/keys", dependencies=[Depends(require_api_key)])
async def list_consumer_keys() -> dict:
    rows = await db.pool().fetch(
        f"SELECT {_KEY_COLUMNS} FROM consumer_keys ORDER BY created_at DESC"
    )
    return {"keys": [_public(row) for row in rows]}


@router.delete("/api/admin/keys/{key_id}", dependencies=[Depends(require_api_key)])
async def revoke_consumer_key(key_id: str) -> dict:
    """Revoking twice is fine: revoked_at is set once and never moved."""
    row = await db.pool().fetchrow(
        "UPDATE consumer_keys SET revoked_at = COALESCE(revoked_at, now()) "
        "WHERE id = $1 RETURNING id, revoked_at",
        key_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="key not found")
    return {"ok": True, "id": dict(row)["id"], "revoked_at": dict(row)["revoked_at"]}
