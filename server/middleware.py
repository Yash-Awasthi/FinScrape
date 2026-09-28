"""Phase 8 hardening wiring: rate limiting, ETag/304, security headers, error envelopes.

One installer, `configure_hardening(app)`, called from the app factory. Kept out of
app.py so the factory stays a readable table of contents.
"""

from __future__ import annotations

import hashlib
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from server.rate_limit import Limiter, client_key
from server.settings import get_settings

log = logging.getLogger("worldfin.hardening")

# API responses are pure JSON with no inline assets — lock the CSP all the way down.
# The SPA's looser CSP (scripts, connect-src, etc.) lives on nginx, not here.
_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"


def _envelope(status: int, message: str) -> JSONResponse:
    """Uniform error shape so clients never have to guess the body schema."""
    return JSONResponse(
        {"error": {"status": status, "message": message}}, status_code=status
    )


def _etag_matches(if_none_match: str, etag: str) -> bool:
    """RFC 9110 If-None-Match: `*` or a list, compared weakly (W/ prefix ignored)."""
    if if_none_match.strip() == "*":
        return True
    ours = etag.removeprefix("W/")
    return any(t.strip().removeprefix("W/") == ours for t in if_none_match.split(","))


def configure_hardening(app: FastAPI) -> None:
    s = get_settings()
    limiter = Limiter(s.rate_limit_per_min)

    # --- structured error envelopes (every error path → {"error": {...}}) ---
    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException) -> Response:
        resp = _envelope(exc.status_code, str(exc.detail))
        # preserve auth challenge / Retry-After style headers if a route set them
        if exc.headers:
            resp.headers.update(exc.headers)
        return resp

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(
        request: Request, exc: RequestValidationError
    ) -> Response:
        return _envelope(422, "validation error")

    @app.exception_handler(Exception)
    async def _unhandled_exc(request: Request, exc: Exception) -> Response:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return _envelope(500, "internal server error")

    # Middleware registration order matters: the LAST registered runs OUTERMOST.
    # We want, outer→inner: security_headers → rate_limit → etag → route, so that
    # *every* response (including 304s and 429s) carries the security headers.

    # --- ETag / 304 on GET JSON (skip cheap revalidation of unchanged payloads) ---
    if s.enable_etag:

        @app.middleware("http")
        async def _etag(request: Request, call_next) -> Response:
            resp = await call_next(request)
            ctype = resp.headers.get("content-type", "")
            if (
                request.method != "GET"
                or resp.status_code != 200
                or "json" not in ctype
            ):
                return resp
            body = b"".join([chunk async for chunk in resp.body_iterator])
            etag = 'W/"' + hashlib.sha1(body).hexdigest() + '"'
            if _etag_matches(request.headers.get("if-none-match", ""), etag):
                not_modified = Response(status_code=304)
                not_modified.headers["ETag"] = etag
                return not_modified
            out = Response(
                content=body,
                status_code=200,
                media_type=resp.media_type or "application/json",
            )
            # carry forward original headers, then stamp the validator
            for k, v in resp.headers.items():
                if k.lower() not in ("content-length", "content-type"):
                    out.headers[k] = v
            out.headers["ETag"] = etag
            return out

    # --- rate limit (trip before doing route work) ---
    @app.middleware("http")
    async def _rate_limit(request: Request, call_next) -> Response:
        allowed, retry = limiter.hit(client_key(request))
        if not allowed:
            resp = _envelope(429, "rate limit exceeded")
            resp.headers["Retry-After"] = str(retry)
            return resp
        return await call_next(request)

    # --- security headers on every response (registered last → outermost) ---
    @app.middleware("http")
    async def _security_headers(request: Request, call_next) -> Response:
        resp = await call_next(request)
        resp.headers.setdefault("X-API-Version", "1.0.0")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Content-Security-Policy", _API_CSP)
        if s.enable_hsts:
            resp.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return resp
