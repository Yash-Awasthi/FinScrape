"""Turn a FastAPI OpenAPI document into the request examples the docs show.

One source for the live page (GET /docs/getting-started) and the Postman generator
(scripts/postman.py): a request is a path with its parameters filled, the query string
an endpoint requires, the JSON body its schema declares and the `X-API-Key` header its
operation carries. Keeping the walk here means the page, the collection and the tests
cannot describe the same endpoint three different ways.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote, urlencode

METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
API_KEY_HEADER = "X-API-Key"

# `require_api_key` is a FastAPI dependency, so the OpenAPI operation carries its
# `x-api-key` header parameter rather than a `security` block. Either counts.

# Values a reader recognises; everything else is derived from the schema.
_SAMPLES = {
    "symbol": "AAPL",
    "date": "2026-01-01",
    "subject": "Demo Corp beats estimates",
    "event_type": "earnings",
    "verdict": "INVEST",
}
_FORMAT_SAMPLES = {
    "date": "2026-01-01",
    "date-time": "2026-01-01T00:00:00Z",
    "uuid": "00000000-0000-0000-0000-000000000000",
}
_ALTERNATION = re.compile(r"[A-Za-z0-9_]+")
_MAX_DEPTH = 8


def iter_operations(spec: dict[str, Any]):
    """Every (path, method, operation) in a deterministic order."""
    for path in sorted(spec.get("paths") or {}):
        ops = spec["paths"][path] or {}
        for method in sorted(ops):
            if method in METHODS:
                yield path, method, ops[method] or {}


def folder_of(path: str) -> str:
    """The group a path belongs to: the segment after `/api`, else the first one."""
    segments = [part for part in path.split("/") if part]
    if not segments:
        return "root"
    if segments[0] == "api" and len(segments) > 1:
        return segments[1]
    return segments[0]


def requires_api_key(op: dict[str, Any]) -> bool:
    """True when the operation publishes (or declares) the API-key header."""
    if op.get("security"):
        return True
    return any(
        str(param.get("name", "")).lower() == "x-api-key"
        and param.get("in") == "header"
        for param in op.get("parameters") or []
    )


def query_parameters(op: dict[str, Any]) -> list[dict[str, Any]]:
    params = [
        param
        for param in op.get("parameters") or []
        if param.get("in") == "query" and "name" in param
    ]
    return sorted(params, key=lambda param: str(param["name"]))


def path_parameters(op: dict[str, Any]) -> list[dict[str, Any]]:
    params = [
        param
        for param in op.get("parameters") or []
        if param.get("in") == "path" and "name" in param
    ]
    return sorted(params, key=lambda param: str(param["name"]))


def body_example(spec: dict[str, Any], op: dict[str, Any]) -> Any:
    """The JSON body an operation takes, or None when it takes none."""
    content = (op.get("requestBody") or {}).get("content") or {}
    media = content.get("application/json") or content.get(
        next(iter(sorted(content)), "") or ""
    )
    schema = (media or {}).get("schema")
    if not schema:
        return None
    return example(spec, schema)


def example(
    spec: dict[str, Any],
    schema: Any,
    *,
    seen: tuple[str, ...] = (),
    depth: int = 0,
    name: str = "",
) -> Any:
    """A minimal valid value for `schema`: required fields only, sane zero values."""
    if not isinstance(schema, dict) or depth > _MAX_DEPTH:
        return {}
    ref = schema.get("$ref")
    if isinstance(ref, str):
        if ref in seen:
            return {}
        resolved = _resolve_ref(spec, ref)
        if not resolved:
            return {}
        return example(spec, resolved, seen=(*seen, ref), depth=depth + 1, name=name)
    for union in ("anyOf", "oneOf"):
        branches = schema.get(union)
        if isinstance(branches, list) and branches:
            for branch in branches:
                if not _is_null(branch):
                    return example(spec, branch, seen=seen, depth=depth + 1, name=name)
            return None
    if "const" in schema:
        return schema["const"]
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]
    if "default" in schema:
        return schema["default"]

    kind = schema.get("type")
    if kind is None and "properties" in schema:
        kind = "object"
    if kind == "object":
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        return {
            field: example(
                spec, properties[field], seen=seen, depth=depth + 1, name=field
            )
            for field in sorted(required)
            if field in properties
        }
    if kind == "array":
        item = example(spec, schema.get("items") or {}, seen=seen, depth=depth + 1)
        return [item] if item not in (None, {}, []) else []
    if kind == "integer":
        floor = schema.get("minimum")
        return int(floor) if isinstance(floor, (int, float)) else 1
    if kind == "number":
        floor = schema.get("minimum")
        return float(floor) if isinstance(floor, (int, float)) else 0.0
    if kind == "boolean":
        return False
    if kind == "string":
        return _string_sample(schema, name)
    return {}


def sample_value(spec: dict[str, Any], param: dict[str, Any], name: str = "") -> Any:
    """The value shown for one parameter, typed values stringified by the caller."""
    schema = param.get("schema") or {}
    return example(spec, schema, name=name or str(param.get("name", "")))


def filled_path(spec: dict[str, Any], path: str, op: dict[str, Any]) -> str:
    """`/api/events/{event_id}` with each parameter replaced by a sample value."""
    schemas = {str(p["name"]): p for p in path_parameters(op)}

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        param = schemas.get(name) or {}
        value = sample_value(spec, param, name)
        return quote(str(value), safe="")

    return re.sub(r"\{([^}]+)\}", substitute, path)


def curl(
    spec: dict[str, Any],
    path: str,
    method: str,
    op: dict[str, Any],
    base_url: str,
    *,
    api_key: str = "local-dev-key",
) -> str:
    """One copy-paste command for an operation, required inputs only."""
    url = base_url.rstrip("/") + filled_path(spec, path, op)
    required = [param for param in query_parameters(op) if param.get("required")]
    if required:
        query = urlencode(
            [(str(param["name"]), str(sample_value(spec, param))) for param in required]
        )
        url = f"{url}?{query}"

    parts = [f"curl -s -X {method.upper()} '{url}'"]
    if requires_api_key(op):
        parts.append(f'-H "X-API-Key: {api_key}"')
    body = body_example(spec, op)
    if body is not None:
        parts.append("-H 'Content-Type: application/json'")
        parts.append(f"--data '{json.dumps(body, sort_keys=True)}'")
    return " \\\n  ".join(parts)


def _resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    prefix = "#/components/schemas/"
    if not ref.startswith(prefix):
        return {}
    schema = (spec.get("components") or {}).get("schemas") or {}
    resolved = schema.get(ref.removeprefix(prefix))
    return resolved if isinstance(resolved, dict) else {}


def _is_null(schema: Any) -> bool:
    return isinstance(schema, dict) and schema.get("type") == "null"


def _string_sample(schema: dict[str, Any], name: str) -> str:
    if name in _SAMPLES:
        return _SAMPLES[name]
    pattern = schema.get("pattern")
    if isinstance(pattern, str):
        inner = pattern.removeprefix("^").removesuffix("$")
        if inner.startswith("(") and inner.endswith(")"):
            options = inner[1:-1].split("|")
            if options and all(_ALTERNATION.fullmatch(o) for o in options):
                return options[0]
    fmt = schema.get("format")
    if isinstance(fmt, str) and fmt in _FORMAT_SAMPLES:
        return _FORMAT_SAMPLES[fmt]
    return "string"
