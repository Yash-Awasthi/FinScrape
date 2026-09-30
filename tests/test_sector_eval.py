"""Sector accuracy of the keyword and company chain on a fixed gold set.

`python -m tests.test_sector_eval` scores the same set with Laya's view added.
"""

import json
from pathlib import Path

from finscrape.analysis import laya
from finscrape.analysis.nlp import FinancialNLP
from finscrape.analysis.ticker_map import resolve_company_tickers

_GOLD = json.loads(
    (Path(__file__).parent / "fixtures" / "sector_gold.json").read_text(encoding="utf-8")
)["cases"]
# Measured when the gold set was written; a drop below it is a regression.
_FLOOR = 0.63


def accuracy(use_laya: bool) -> tuple[float, list[tuple[str, str, str]]]:
    nlp = FinancialNLP()
    misses = []
    for case in _GOLD:
        subject = case["subject"]
        view = laya.classify(subject, "") if use_laya else None
        got = laya.choose_sector(
            "", view, nlp.analyze(subject, "").sector, tickers=resolve_company_tickers(subject)
        )
        if got != case["sector"]:
            misses.append((subject, case["sector"], got))
    return 1 - len(misses) / len(_GOLD), misses


def test_sector_accuracy_without_laya():
    score, misses = accuracy(use_laya=False)
    print(f"\nsector accuracy without Laya: {score:.1%} of {len(_GOLD)}")
    assert score >= _FLOOR, misses


if __name__ == "__main__":
    score, misses = accuracy(use_laya=True)
    for subject, want, got in misses:
        print(f"  want {want:14} got {got:14} {subject}")
    print(f"sector accuracy with Laya: {score:.1%} of {len(_GOLD)}")
