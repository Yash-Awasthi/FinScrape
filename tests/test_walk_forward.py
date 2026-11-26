"""Walk-forward evaluation: month buckets, frozen prompts, no look-ahead (plan M5.2).

The shipped gold set carries no dates, so the mechanism is proved on a dated slice built
here from copies of real gold rows plus a fixture date. The fixture dates are test data,
not a claim about when those headlines happened.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import eval_model

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "tests" / "gold" / "sector_set.jsonl"
RECORDING = ROOT / "tests" / "gold" / "recordings" / "keyword-baseline.jsonl"

# 40 real gold rows, spread over three months. The month a row gets is fixture data.
SLICE = [(i, month) for i, month in enumerate(
    ["2026-09"] * 14 + ["2026-10"] * 13 + ["2026-11"] * 13, start=1
)]


def _dated_gold(tmp_path: Path) -> Path:
    rows = [json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines()]
    by_id = {row["id"]: row for row in rows}
    path = tmp_path / "dated_sector_set.jsonl"
    lines = []
    for case_id, month in SLICE:
        row = dict(by_id[case_id])
        row["published_at"] = f"{month}-15"
        lines.append(json.dumps(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _dated_recording(tmp_path: Path) -> Path:
    lines = RECORDING.read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    by_id = {json.loads(line)["id"]: line for line in lines[1:]}
    assert header["kind"] == "eval-recording"
    path = tmp_path / "dated_recording.jsonl"
    path.write_text(
        "\n".join([lines[0]] + [by_id[case_id] for case_id, _ in SLICE]) + "\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def dated_run(tmp_path: Path) -> tuple[Path, Path]:
    return _dated_gold(tmp_path), _dated_recording(tmp_path)


def test_month_periods_cover_the_fixture_once(dated_run: tuple[Path, Path]) -> None:
    gold, _ = dated_run
    cases = eval_model.load_gold(gold)
    assert all(case.published_at for case in cases)
    buckets = eval_model.walk_forward_split(cases)
    assert sorted(buckets) == ["2026-09", "2026-10", "2026-11"]
    assert [len(buckets[m]) for m in sorted(buckets)] == [14, 13, 13]
    assert sum(len(rows) for rows in buckets.values()) == 40


def test_a_later_month_cannot_be_scored_in_an_earlier_period() -> None:
    case = eval_model.Case(
        id=1, subject="x", sector="energy", verdict=None, reason="", provenance="",
        published_at="2026-10-01",
    )
    with pytest.raises(eval_model.LookAheadError):
        eval_model.assert_within_period("2026-09", case)
    eval_model.assert_within_period("2026-10", case)


def test_undated_case_is_refused_not_guessed() -> None:
    case = eval_model.Case(
        id=2, subject="x", sector="energy", verdict=None, reason="", provenance=""
    )
    with pytest.raises(eval_model.LookAheadError, match="carries no date"):
        eval_model.walk_forward_split([case])


def test_the_shipped_gold_set_is_refused_with_the_exact_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = eval_model.main(
        ["--replay", str(RECORDING), "--walk-forward"]
    )
    out = capsys.readouterr().out
    assert code == 2
    assert "walk-forward needs dated cases: 243 of 243 carry no date" in out


def test_per_month_report_and_frozen_prompt_ledger(
    dated_run: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gold, recording = dated_run
    ledger = tmp_path / "frozen.json"
    code = eval_model.main(
        [
            "--gold",
            str(gold),
            "--replay",
            str(recording),
            "--walk-forward",
            "--frozen-prompts",
            str(ledger),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    for month, cases in (("2026-09", 14), ("2026-10", 13), ("2026-11", 13)):
        line = next(ln for ln in out.splitlines() if ln.startswith(month))
        assert f"{cases:>5}" in line, line
    assert "one period only" not in out
    frozen = json.loads(ledger.read_text(encoding="utf-8"))
    fingerprints = set(frozen["periods"].values())
    assert sorted(frozen["periods"]) == ["2026-09", "2026-10", "2026-11"]
    assert len(fingerprints) == 1
    assert fingerprints == {eval_model.prompt_fingerprint_for("v1")}


def test_prompt_change_inside_a_period_is_refused(
    dated_run: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gold, recording = dated_run
    ledger = tmp_path / "frozen.json"
    assert (
        eval_model.main(
            [
                "--gold",
                str(gold),
                "--replay",
                str(recording),
                "--walk-forward",
                "--frozen-prompts",
                str(ledger),
            ]
        )
        == 0
    )
    capsys.readouterr()
    frozen = json.loads(ledger.read_text(encoding="utf-8"))
    frozen["periods"]["2026-10"] = "0000000000000000"
    ledger.write_text(json.dumps(frozen), encoding="utf-8")

    code = eval_model.main(
        [
            "--gold",
            str(gold),
            "--replay",
            str(recording),
            "--walk-forward",
            "--frozen-prompts",
            str(ledger),
        ]
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "period 2026-10 was scored with prompt 0000000000000000" in out


def test_load_gold_reads_a_date_field_but_leaves_the_shipped_set_dateless() -> None:
    shipped = eval_model.load_gold(GOLD)
    assert shipped and all(case.published_at == "" for case in shipped)
