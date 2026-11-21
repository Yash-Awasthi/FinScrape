"""Snapshot the public API contract and refuse a breaking change to it.

The frontend, the Telegram bot and the landing page all read this API. A removed path,
a removed query parameter, a newly required one, a tighter bound or a dropped response
field breaks them silently — nothing fails until a user sees an empty panel.

    python -m scripts.openapi_snapshot --write   # after an intended contract change
    python -m scripts.openapi_snapshot --check   # CI: non-zero on a regression

The comparison is deliberately one-directional: adding a path, a parameter or a response
field is fine (it is additive), and the snapshot stays a superset. Only narrowing fails.
Every regression is printed with the path it belongs to, so the fix is obvious.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "tests" / "snapshots" / "openapi.json"

JSON_TYPES = {
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "array": "array",
    "object": "object",
}


def build() -> dict[str, Any]:
    """The contract, reduced to what clients actually depend on."""
    from server.app import create_app

    raw = create_app().openapi()
    paths: dict[str, Any] = {}
    for path, ops in sorted(raw.get("paths", {}).items()):
        entry: dict[str, Any] = {}
        for method, op in sorted(ops.items()):
            params = {}
            for param in op.get("parameters", []):
                params[param["name"]] = {
                    "in": param.get("in"),
                    "required": bool(param.get("required")),
                    "schema": _schema_shape(param.get("schema") or {}),
                }
            entry[method] = {
                "parameters": params,
                "auth": bool(op.get("security")),
                "responses": {
                    code: _schema_shape(
                        (resp.get("content") or {})
                        .get("application/json", {})
                        .get("schema")
                        or {}
                    )
                    for code, resp in sorted(op.get("responses", {}).items())
                },
            }
        paths[path] = entry
    return {"paths": paths, "components": _components(raw)}


def _components(raw: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for name, schema in sorted(
        (raw.get("components", {}).get("schemas") or {}).items()
    ):
        out[name] = {
            "fields": {
                key: _schema_shape(value)
                for key, value in sorted(schema.get("properties", {}).items())
            },
            "required": sorted(schema.get("required", [])),
        }
    return out


def _schema_shape(schema: dict[str, Any]) -> dict[str, Any]:
    """What a client can rely on: type, nullability, enum and the collection item type."""
    if not schema:
        return {}
    shape: dict[str, Any] = {}
    if "$ref" in schema:
        shape["$ref"] = schema["$ref"].rsplit("/", 1)[-1]
        return shape
    if "anyOf" in schema:
        # Optional[...] / Union[...] — record the branches, not FastAPI's wrapper.
        return {"anyOf": [_schema_shape(branch) for branch in schema["anyOf"]]}
    if "type" in schema:
        shape["type"] = JSON_TYPES.get(schema["type"], schema["type"])
    if "enum" in schema:
        shape["enum"] = sorted(schema["enum"])
    for bound in ("minimum", "maximum", "minLength", "maxLength"):
        if bound in schema:
            shape[bound] = schema[bound]
    if "items" in schema:
        shape["items"] = _schema_shape(schema["items"])
    if "additionalProperties" in schema and isinstance(
        schema["additionalProperties"], dict
    ):
        shape["additionalProperties"] = _schema_shape(schema["additionalProperties"])
    return shape


def compare(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Regressions only: a path/parameter/field that shrank or got stricter."""
    problems: list[str] = []

    old_paths, new_paths = old.get("paths", {}), new.get("paths", {})
    for path in old_paths:
        if path not in new_paths:
            problems.append(f"removed path {path}")
            continue
        for method, old_op in old_paths[path].items():
            new_op = new_paths[path].get(method)
            if new_op is None:
                problems.append(f"removed method {method.upper()} {path}")
                continue
            problems.extend(_compare_op(path, method, old_op, new_op))

    old_components, new_components = (
        old.get("components", {}),
        new.get("components", {}),
    )
    for name, old_schema in old_components.items():
        new_schema = new_components.get(name)
        if new_schema is None:
            problems.append(f"removed schema {name}")
            continue
        for field, old_shape in old_schema["fields"].items():
            if field not in new_schema["fields"]:
                problems.append(f"removed field {name}.{field}")
                continue
            problems.extend(
                _compare_shape(
                    f"{name}.{field}", old_shape, new_schema["fields"][field]
                )
            )
        for field in old_schema["required"]:
            if field not in new_schema["required"]:
                problems.append(f"field became optional {name}.{field}")
    return problems


def _compare_op(path: str, method: str, old_op: dict, new_op: dict) -> list[str]:
    where = f"{method.upper()} {path}"
    problems: list[str] = []
    old_params, new_params = old_op["parameters"], new_op["parameters"]
    for name, old_param in old_params.items():
        new_param = new_params.get(name)
        if new_param is None:
            problems.append(f"{where}: removed parameter {name}")
            continue
        if new_param["required"] and not old_param["required"]:
            problems.append(f"{where}: parameter {name} became required")
        problems.extend(
            _compare_shape(f"{where} ?{name}", old_param["schema"], new_param["schema"])
        )
    for code, old_shape in old_op["responses"].items():
        new_shape = new_op["responses"].get(code)
        if new_shape is None:
            problems.append(f"{where}: removed response {code}")
            continue
        problems.extend(_compare_shape(f"{where} {code}", old_shape, new_shape))
    if old_op["auth"] and not new_op["auth"]:
        problems.append(f"{where}: authentication dropped")
    return problems


def _compare_shape(where: str, old: dict, new: dict) -> list[str]:
    if old == new or not old:
        return []
    problems = []
    if old.get("type") and old["type"] != new.get("type") and "$ref" not in old:
        problems.append(f"{where}: type changed {old['type']} → {new.get('type')}")
    for bound, label in (
        ("minimum", "min"),
        ("maximum", "max"),
        ("minLength", "min length"),
        ("maxLength", "max length"),
    ):
        if bound in old and bound in new and new[bound] != old[bound]:
            # A raised floor or a lowered ceiling is stricter; the reverse is a loosening.
            floor = bound in ("minimum", "minLength")
            tighter = new[bound] > old[bound] if floor else new[bound] < old[bound]
            if tighter:
                problems.append(
                    f"{where}: {label} narrowed {old[bound]} → {new[bound]}"
                )
    if "enum" in old and "enum" in new:
        lost = set(old["enum"]) - set(new["enum"])
        if lost:
            problems.append(f"{where}: dropped enum values {sorted(lost)}")
    if "items" in old and "items" in new:
        problems.extend(_compare_shape(f"{where}[]", old["items"], new["items"]))
    if "anyOf" in old and "anyOf" in new:
        before = {json.dumps(branch, sort_keys=True) for branch in old["anyOf"]}
        after = {json.dumps(branch, sort_keys=True) for branch in new["anyOf"]}
        if before - after:
            problems.append(f"{where}: union lost a branch")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--write", action="store_true", help="overwrite the snapshot")
    parser.add_argument("--check", action="store_true", help="fail on a regression")
    parser.add_argument("--out", default=str(SNAPSHOT), help="snapshot path")
    args = parser.parse_args(argv)
    out = Path(args.out)

    current = build()
    if args.write or not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        paths = len(current["paths"])
        print(
            f"openapi_snapshot: wrote {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out} ({paths} paths)"
        )
        return 0

    problems = compare(json.loads(out.read_text(encoding="utf-8")), current)
    if not problems:
        print(
            f"openapi_snapshot: {len(current['paths'])} paths, no contract regression"
        )
        return 0
    for problem in problems:
        print(f"  BREAKING {problem}")
    print(
        f"openapi_snapshot: {len(problems)} breaking change(s). If they are intended, "
        f"run `python -m scripts.openapi_snapshot --write` and note the change in docs/DEPLOY.md."
    )
    return 1 if args.check or not args.write else 0


if __name__ == "__main__":
    sys.exit(main())
