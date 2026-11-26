"""Generate a Postman v2.1 collection from the live OpenAPI contract.

    python -m scripts.postman > collection.json            # print
    python -m scripts.postman --write docs/postman.json    # refresh the committed file
    python -m scripts.postman --check docs/postman.json    # CI: fail when stale

The collection is built from `create_app().openapi()`, never hand-edited: one request
per path+method, a folder per path prefix (the segment after `/api`), query parameters
from the operation, a JSON body from the request schema (required fields only), and an
`X-API-Key` header wherever the operation publishes one. Ids are uuid5 of the method and
path and nothing records a timestamp, so a re-run over an unchanged contract produces a
byte-identical file.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from server import openapi_examples as examples

ROOT = Path(__file__).resolve().parent.parent
COLLECTION = ROOT / "docs" / "postman.json"
SCHEMA_URL = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
_NAMESPACE = uuid.UUID("6f0d7c3e-8b0a-4a63-9a1e-2b7c9f0d4e11")
_AUTH_HEADERS = frozenset({"x-api-key", "authorization"})
_BASE_URL = "http://localhost:8010"
_DESCRIPTION = (
    "One request per endpoint, generated from the OpenAPI schema. Set the baseUrl and "
    "apiKey collection variables; the apiKey default is the published development key. "
    "Every request marked with an X-API-Key header needs it."
)


def build(
    spec: dict[str, Any] | None = None, *, api_key: str | None = None
) -> dict[str, Any]:
    """The whole collection; `spec` defaults to the live app's OpenAPI document."""
    if spec is None:
        from server.app import create_app

        spec = create_app().openapi()
    if api_key is None:
        from server.settings import DEFAULT_API_KEY

        api_key = DEFAULT_API_KEY

    folders: dict[str, list[dict[str, Any]]] = {}
    for path, method, op in examples.iter_operations(spec):
        folders.setdefault(examples.folder_of(path), []).append(
            _item(spec, path, method, op)
        )

    return {
        "info": {
            "_postman_id": _uid("collection"),
            "name": "FinScrape API",
            "description": _DESCRIPTION,
            "schema": SCHEMA_URL,
        },
        "variable": [
            {"key": "baseUrl", "value": _BASE_URL, "type": "string"},
            {"key": "apiKey", "value": api_key, "type": "string"},
        ],
        "item": [
            {
                "id": _uid(f"folder:{folder}"),
                "name": folder,
                "item": sorted(folders[folder], key=lambda item: item["name"]),
            }
            for folder in sorted(folders)
        ],
    }


def count(collection: dict[str, Any]) -> int:
    return sum(len(folder["item"]) for folder in collection["item"])


def dumps(collection: dict[str, Any]) -> str:
    """The committed bytes: sorted keys, ASCII escapes, trailing newline."""
    return json.dumps(collection, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _item(
    spec: dict[str, Any], path: str, method: str, op: dict[str, Any]
) -> dict[str, Any]:
    headers: list[dict[str, Any]] = []
    if examples.requires_api_key(op):
        headers.append(
            {"key": examples.API_KEY_HEADER, "value": "{{apiKey}}", "type": "text"}
        )
    for param in op.get("parameters") or []:
        name = str(param.get("name", ""))
        if (
            param.get("in") == "header"
            and param.get("required")
            and name.lower() not in _AUTH_HEADERS
        ):
            headers.append(
                {
                    "key": name,
                    "value": str(examples.sample_value(spec, param, name)),
                    "type": "text",
                }
            )

    query: list[dict[str, Any]] = []
    for param in examples.query_parameters(op):
        name = str(param["name"])
        entry: dict[str, Any] = {
            "key": name,
            "value": str(examples.sample_value(spec, param, name)),
        }
        if param.get("description"):
            entry["description"] = param["description"]
        if not param.get("required"):
            entry["disabled"] = True
        query.append(entry)

    url_path = examples.filled_path(spec, path, op)
    raw = "{{baseUrl}}" + url_path
    enabled = [entry for entry in query if not entry.get("disabled")]
    if enabled:
        raw += "?" + urlencode([(entry["key"], entry["value"]) for entry in enabled])

    request: dict[str, Any] = {
        "method": method.upper(),
        "header": headers,
        "url": {
            "raw": raw,
            "host": ["{{baseUrl}}"],
            "path": [segment for segment in url_path.split("/") if segment],
            "query": query,
        },
        "description": _description(op),
    }
    body = examples.body_example(spec, op)
    if body is not None:
        request["body"] = {
            "mode": "raw",
            "raw": json.dumps(body, indent=2, sort_keys=True),
            "options": {"raw": {"language": "json"}},
        }

    label = f"{method.upper()} {path}"
    return {
        "id": _uid(label),
        "name": label,
        "request": request,
        "response": [],
    }


def _description(op: dict[str, Any]) -> str:
    text = op.get("summary") or op.get("description") or ""
    return " ".join(str(text).split())


def _uid(key: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, key))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--write",
        nargs="?",
        const=str(COLLECTION),
        metavar="PATH",
        help="write the collection (default docs/postman.json)",
    )
    parser.add_argument(
        "--check",
        nargs="?",
        const=str(COLLECTION),
        metavar="PATH",
        help="fail when PATH does not match the generated collection",
    )
    args = parser.parse_args(argv)

    collection = build()
    text = dumps(collection)
    requests = count(collection)

    if args.write:
        out = Path(args.write)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"postman: wrote {_shown(out)} ({requests} requests)")
        return 0

    if args.check:
        out = Path(args.check)
        if not out.is_file():
            print(
                f"postman: {_shown(out)} is missing; "
                "run `python -m scripts.postman --write docs/postman.json`"
            )
            return 1
        if out.read_text(encoding="utf-8") != text:
            print(
                f"postman: {_shown(out)} is stale; "
                "run `python -m scripts.postman --write docs/postman.json`"
            )
            return 1
        print(f"postman: {_shown(out)} matches the contract ({requests} requests)")
        return 0

    sys.stdout.write(text)
    return 0


def _shown(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


if __name__ == "__main__":
    sys.exit(main())
