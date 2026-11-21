"""Tests for the pyright baseline generator (`scripts/pyright_baseline.py`).

The generator itself is not run here — one pyright run takes about a minute, and the CI job
`pyright-baseline` runs `--check` against the real tree. These tests pin the parsing and the
ratchet rules on recorded output.
"""

from __future__ import annotations

import json

from scripts.pyright_baseline import new_hits, parse_fingerprint, render, total

SAMPLE = json.dumps(
    {
        "version": "1.1.414",
        "generalDiagnostics": [
            {
                "file": "c:/repo/finscrape/market_data.py",
                "severity": "error",
                "message": 'Cannot access attribute "iloc" for class "ndarray"',
                "range": {"start": {"line": 1, "character": 4}},
                "rule": "reportAttributeAccessIssue",
            },
            {
                "file": "c:/repo/finscrape/market_data.py",
                "severity": "error",
                "message": 'Cannot access attribute "reindex"',
                "rule": "reportAttributeAccessIssue",
            },
            {
                "file": "c:/repo/server/app.py",
                "severity": "error",
                "message": 'Argument of type "int" cannot be assigned',
                "rule": "reportArgumentType",
            },
            {
                "file": "c:/repo/server/app.py",
                "severity": "warning",
                "message": "unused variable",
                "rule": "reportUnusedVariable",
            },
        ],
        "summary": {"errorCount": 3, "warningCount": 1, "informationCount": 0},
    }
)


def test_errors_are_grouped_per_file_and_rule():
    found = parse_fingerprint(SAMPLE)

    assert found == {
        "finscrape/market_data.py": {"reportAttributeAccessIssue": 2},
        "server/app.py": {"reportArgumentType": 1},
    }


def test_warnings_are_not_debt():
    assert total(parse_fingerprint(SAMPLE)) == 3


def test_line_numbers_do_not_change_the_fingerprint():
    moved = SAMPLE.replace('"line": 1', '"line": 900')
    assert parse_fingerprint(moved) == parse_fingerprint(SAMPLE)


def test_a_new_kind_of_error_in_a_known_file_is_new_debt():
    baseline = parse_fingerprint(SAMPLE)
    current = json.loads(SAMPLE)
    current["generalDiagnostics"].append(
        {
            "file": "c:/repo/finscrape/market_data.py",
            "severity": "error",
            "message": "Undefined name",
            "rule": "reportUndefinedVariable",
        }
    )

    hits = new_hits(baseline, parse_fingerprint(json.dumps(current)))

    assert len(hits) == 1
    assert "reportUndefinedVariable" in hits[0]


def test_more_of_the_same_error_is_new_debt():
    baseline = parse_fingerprint(SAMPLE)
    current = json.loads(SAMPLE)
    current["generalDiagnostics"].append(
        {
            "file": "c:/repo/server/app.py",
            "severity": "error",
            "message": "another one",
            "rule": "reportArgumentType",
        }
    )

    hits = new_hits(baseline, parse_fingerprint(json.dumps(current)))

    assert hits == ["server/app.py: reportArgumentType x2 (baseline 1)"]


def test_debt_may_shrink_freely():
    baseline = parse_fingerprint(SAMPLE)
    current = json.loads(SAMPLE)
    current["generalDiagnostics"] = [
        row
        for row in current["generalDiagnostics"]
        if row.get("rule") != "reportArgumentType"
    ]

    assert new_hits(baseline, parse_fingerprint(json.dumps(current))) == []


def test_the_document_lists_rules_and_files():
    text = render(parse_fingerprint(SAMPLE))

    assert "**3 errors in 2 files.**" in text
    assert "| 2 | `reportAttributeAccessIssue` |" in text
    assert "`finscrape/market_data.py`" in text


def test_unparseable_output_means_no_debt():
    # pyright crashing must not silently look like a clean tree *and* must not crash the gate;
    # the CI job fails on the stale fingerprint instead.
    assert parse_fingerprint("not json") == {}
