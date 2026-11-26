"""The frozen public sample behind the walk-forward run (plan M5.2).

Proves the file is the one the manifest hashed, that every row is dated, and that each
sector label follows the SIC rule in the script that built it. Offline: no network.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import eval_model
from scripts.gold_public_sample import sector_for

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "tests" / "gold" / "public_sample_2026_09_10.jsonl"
MANIFEST = ROOT / "tests" / "gold" / "public_sample_2026_09_10.manifest.json"
PROMPTS = ROOT / "tests" / "gold" / "public_sample_2026_09_10.prompts.json"


def _rows() -> list[dict]:
    return [json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines()]


def test_manifest_hash_matches_the_frozen_file() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    digest = hashlib.sha256(GOLD.read_bytes()).hexdigest()
    assert manifest["sha256"] == digest
    assert manifest["rows"] == len(_rows())
    assert manifest["label"] == "public sample, not production"
    assert "EDGAR" in manifest["source"]


def test_every_row_is_dated_across_two_months() -> None:
    rows = _rows()
    assert [row["id"] for row in rows] == list(range(1, len(rows) + 1))
    months = {row["published_at"][:7] for row in rows}
    assert months == {"2026-09", "2026-10"}
    cases = eval_model.load_gold(GOLD)
    assert all(case.published_at for case in cases)
    assert sorted(eval_model.walk_forward_split(cases)) == ["2026-09", "2026-10"]


def test_labels_follow_the_sic_rule_and_stay_honest() -> None:
    for row in _rows():
        assert row["sector"] in eval_model.SECTORS
        sic = row["reason"].split("EDGAR SIC ")[1].split()[0]
        assert sector_for(sic) == row["sector"], row
        assert row["verdict"] is None, "a filing is not a direction call"
        assert "accession" in row["provenance"]


def test_prompt_fingerprint_is_frozen_per_period() -> None:
    periods = json.loads(PROMPTS.read_text(encoding="utf-8"))["periods"]
    assert sorted(periods) == ["2026-09", "2026-10"]
    assert len(set(periods.values())) == 1
