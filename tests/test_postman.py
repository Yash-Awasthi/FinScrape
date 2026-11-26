"""docs/postman.json is generated from the live contract, not hand-maintained.

The collection is a second, clickable view of the API: if an endpoint is added, renamed
or starts requiring the key, the committed file has to move with it. `--check` is the
gate; these tests prove the generator describes exactly the schema it reads.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pydantic_settings")

from scripts import postman
from server import openapi_examples as examples

ROOT = Path(__file__).resolve().parents[1]
COLLECTION = ROOT / "docs" / "postman.json"


def _spec() -> dict:
    from server.app import create_app

    return create_app().openapi()


def _requests(collection: dict):
    for folder in collection["item"]:
        for item in folder["item"]:
            method, path = item["name"].split(" ", 1)
            yield folder["name"], method.lower(), path, item


def test_generation_is_deterministic():
    spec = _spec()
    first = postman.dumps(postman.build(spec))
    second = postman.dumps(postman.build(spec))
    assert first == second
    assert json.loads(first) == postman.build(spec)


def test_one_request_per_path_and_method():
    spec = _spec()
    collection = postman.build(spec)
    expected = {(path, method) for path, method, _ in examples.iter_operations(spec)}
    actual = [(path, method) for _, method, path, _ in _requests(collection)]
    assert len(actual) == len(expected), "a request is missing or duplicated"
    assert set(actual) == expected


def test_every_request_is_grouped_and_shaped_like_a_postman_request():
    collection = postman.build(_spec())
    for folder, method, path, item in _requests(collection):
        assert folder == examples.folder_of(path)
        request = item["request"]
        assert request["method"] == method.upper()
        assert request["url"]["raw"].startswith("{{baseUrl}}" + path.split("{")[0])
        assert request["url"]["host"] == ["{{baseUrl}}"]


def test_the_auth_header_is_exactly_where_the_operation_declares_it():
    spec = _spec()
    declared = {
        (path, method): examples.requires_api_key(op)
        for path, method, op in examples.iter_operations(spec)
    }
    assert any(declared.values()), "no operation declares the key; the walk is wrong"
    for _, method, path, item in _requests(postman.build(spec)):
        headers = {header["key"].lower() for header in item["request"]["header"]}
        assert ("x-api-key" in headers) == declared[(path, method)], path
        assert "authorization" not in headers


def test_the_body_example_is_built_from_the_request_schema():
    spec = _spec()
    for path, method, op in examples.iter_operations(spec):
        body = examples.body_example(spec, op)
        if (op.get("requestBody") or {}).get("content"):
            assert body is not None, f"{method.upper()} {path} lost its body example"


def test_stdout_is_the_collection(capsys):
    assert postman.main([]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == postman.build()


def test_the_committed_collection_is_current():
    assert COLLECTION.is_file(), (
        "run `python -m scripts.postman --write docs/postman.json`"
    )
    assert postman.main(["--check", str(COLLECTION)]) == 0
