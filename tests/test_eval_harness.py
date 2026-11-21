"""The gold set gates a model or prompt change (plan M2.1).

Three things are checked: the benchmark itself is well-formed and frozen, the offline
replay reproduces the stored baseline, and a run that loses more than five points of
sector accuracy is refused.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts import eval_model

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "tests" / "gold" / "sector_set.jsonl"
RECORDING = ROOT / "tests" / "gold" / "recordings" / "keyword-baseline.jsonl"


def test_the_gold_set_is_well_formed_and_frozen():
    cases = eval_model.load_gold(GOLD)
    assert len(cases) == 243
    assert [c.id for c in cases] == list(range(1, 244))  # stable ids, never renumbered
    assert all(c.sector in eval_model.SECTORS for c in cases)
    labelled = [c for c in cases if c.verdict]
    assert len(labelled) == 56  # the model-choice set
    assert all(c.verdict in eval_model.VERDICTS for c in labelled)
    assert all(c.reason for c in cases)  # every label carries its audit line
    assert {c.provenance.split(" ")[0] for c in cases} == {"model-choice", "production"}


def test_the_recording_matches_the_prompt_it_was_recorded_with():
    header = json.loads(RECORDING.read_text(encoding="utf-8").splitlines()[0])
    system, analysis = eval_model._prompt_pair(header["prompt"])
    assert header["prompt_fingerprint"] == eval_model.prompt_fingerprint(
        system, analysis
    )


def test_the_offline_replay_reproduces_the_baseline(capsys, monkeypatch):
    monkeypatch.setenv("FINSCRAPE_LAYA", "0")
    code = eval_model.main(["--replay", str(RECORDING), "--gate"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "sector accuracy 63.8%" in out
    assert "JSON validity   100.0%" in out
    assert "gate: baseline 63.8%" in out


def test_a_stale_recording_is_refused(tmp_path):
    """Editing the prompt must not silently score yesterday's text."""
    lines = RECORDING.read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    header["prompt_fingerprint"] = "0000000000000000"
    stale = tmp_path / "stale.jsonl"
    stale.write_text(
        "\n".join([json.dumps(header), *lines[1:]]) + "\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="stale recording"):
        eval_model.main(["--replay", str(stale)])


def test_a_six_point_drop_is_refused(tmp_path, capsys):
    """plan M2.1: refuse a model switch that costs more than 5 points of sector accuracy."""
    # Score the recording against a docs copy whose baseline row claims 70%.
    doc = tmp_path / "EVAL.md"
    doc.write_text(
        "| Model | Prompt | Date | Sector accuracy | JSON validity | Verdict agreement | Latency p50 / p90 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| keyword-baseline | v1 | 2026-11-24 | 70.0% | 100.0% | 46.4% (56) | 10 / 16 ms |\n",
        encoding="utf-8",
    )
    monkeypatch_target = eval_model.EVAL_DOC
    eval_model.EVAL_DOC = doc
    try:
        code = eval_model.main(["--replay", str(RECORDING), "--gate"])
        out = capsys.readouterr().out
    finally:
        eval_model.EVAL_DOC = monkeypatch_target
    assert code == 1, out
    assert "FAIL" in out and "6.2%" in out


def test_a_model_with_no_baseline_is_recorded_not_blocked(
    tmp_path, capsys, monkeypatch
):
    doc = tmp_path / "EVAL.md"
    doc.write_text(
        "| Model | Prompt | Date | Sector accuracy | JSON validity | Verdict agreement | Latency p50 / p90 |\n|---|---|---|---|---|---|---|\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(eval_model, "EVAL_DOC", doc)
    code = eval_model.main(["--replay", str(RECORDING), "--gate"])
    assert code == 0
    assert "no baseline" in capsys.readouterr().out


def test_append_doc_writes_a_row_the_gate_can_read_back(tmp_path):
    doc = tmp_path / "EVAL.md"
    results, model = eval_model.run_replay(eval_model.load_gold(GOLD), RECORDING, "v1")
    metrics = eval_model.measure(results, model, "v1")
    eval_model.append_doc(metrics, doc)
    assert eval_model.baseline_for(model, "v1", doc) == pytest.approx(
        metrics.sector_accuracy, abs=1e-3
    )


def test_normalisation_reads_the_prose_a_model_actually_writes():
    assert eval_model.normalise_sector("Energy — crude and LNG") == "energy"
    assert eval_model.normalise_sector("Information Technology") == "technology"
    assert eval_model.normalise_sector("defense") == "industrials"
    assert eval_model.normalise_sector("") == "other"


def test_the_recording_is_small_enough_to_keep_in_the_repo():
    assert shutil.disk_usage(RECORDING).used > 0
    assert RECORDING.stat().st_size < 2_000_000
