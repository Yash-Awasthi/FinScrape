"""The sector chain, replayed against the gold set and attributed layer by layer.

Three jobs. The parity test replays `finscrape.signals.sector_chain.decide` over
all 243 gold cases and requires the sector to equal `laya.choose_sector`'s on
every one of them, so the attribution cannot drift from the chain it describes.
The attribution tests pin each layer's label to the evidence that earned it,
including the case where a company outranks a confident Laya view. The report
test walks the gold set once with no LLM label, scores every source on its own,
and registers a terminal-summary plugin so the table survives a plain `pytest -q`
run instead of being swallowed with captured stdout.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from finscrape.analysis import laya
from finscrape.analysis.laya import LayaView
from finscrape.analysis.nlp import FinancialNLP
from finscrape.analysis.ticker_map import resolve_company_tickers
from finscrape.signals.sector_chain import DECIDERS, company_sector, decide

_GOLD: list[dict[str, str]] = json.loads(
    (Path(__file__).parent / "fixtures" / "sector_gold.json").read_text(
        encoding="utf-8"
    )
)["cases"]


@dataclass(frozen=True)
class _Stats:
    """One pass over the gold set, with every source scored against its label."""

    n: int
    parity: int
    attributed: Counter[str]
    correct: Counter[str]
    keyword_correct: int
    company_n: int
    company_correct: int
    laya_n: int
    laya_correct: int
    final_correct: int


@lru_cache(maxsize=1)
def _measure() -> _Stats:
    """Run the chain and each standalone source over the gold set once."""
    nlp = FinancialNLP()
    attributed: Counter[str] = Counter()
    correct: Counter[str] = Counter()
    parity = keyword_correct = company_n = company_correct = 0
    laya_n = laya_correct = final_correct = 0

    for case in _GOLD:
        subject, gold = case["subject"], case["sector"]
        view = laya.classify(subject, "")
        keyword = nlp.analyze(subject, "").sector
        tickers = resolve_company_tickers(subject)
        decision = decide("", view, keyword, tickers=tickers)
        replayed = laya.choose_sector("", view, keyword, tickers=tickers)

        if decision["sector"] == replayed:
            parity += 1
        attributed[decision["decided_by"]] += 1
        if decision["sector"] == gold:
            correct[decision["decided_by"]] += 1
            final_correct += 1
        if keyword == gold:
            keyword_correct += 1
        named = company_sector(tickers)
        if named:
            company_n += 1
            if named == gold:
                company_correct += 1
        if view is not None:
            laya_n += 1
            if view.sector == gold:
                laya_correct += 1

    return _Stats(
        n=len(_GOLD),
        parity=parity,
        attributed=attributed,
        correct=correct,
        keyword_correct=keyword_correct,
        company_n=company_n,
        company_correct=company_correct,
        laya_n=laya_n,
        laya_correct=laya_correct,
        final_correct=final_correct,
    )


def _accuracy(correct: int, total: int) -> str:
    return "n/a" if not total else f"{correct / total:.1%}"


def _build_report() -> list[str]:
    """The terminal table, one ASCII line per measurement."""
    stats = _measure()
    lines = [
        (
            f'Sector chain on the gold set: {stats.n} cases, llm_sector="" '
            "(no offline LLM labels recorded)"
        ),
        f"parity: decide()==laya.choose_sector() on {stats.parity}/{stats.n} cases",
        "attribution: "
        + ", ".join(f"{name} {stats.attributed[name]}" for name in DECIDERS),
    ]
    for name in DECIDERS:
        total = stats.attributed[name]
        lines.append(
            f"decided_by {name:<9}n={total:>4}  "
            f"accuracy {_accuracy(stats.correct[name], total)}"
        )
    if stats.laya_n:
        lines.append(
            f"source {'laya-alone':<14}n={stats.laya_n:>4}  "
            f"accuracy {_accuracy(stats.laya_correct, stats.laya_n)}"
        )
    else:
        lines.append(
            f"source {'laya-alone':<14}n=   0  UNPROVABLE offline: "
            "Laya is not installed and no Laya labels are recorded"
        )
    lines.append(
        f"source {'keyword-alone':<14}n={stats.n:>4}  "
        f"accuracy {_accuracy(stats.keyword_correct, stats.n)} "
        "(empty keyword label counts as a miss)"
    )
    lines.append(
        f"source {'company-alone':<14}n={stats.company_n:>4}  "
        f"accuracy {_accuracy(stats.company_correct, stats.company_n)}"
    )
    lines.append(
        f"source {'final chain':<14}n={stats.n:>4}  "
        f"accuracy {_accuracy(stats.final_correct, stats.n)}"
    )
    return lines


class _TerminalReport:
    """Print the report at session end, where `-q` still shows it."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines

    def pytest_terminal_summary(self, terminalreporter, exitstatus, config) -> None:
        terminalreporter.write_line("")
        terminalreporter.write_line("Sector chain report (M5.1)")
        for line in self.lines:
            terminalreporter.write_line(line)


def test_parity_with_choose_sector_on_every_gold_case() -> None:
    """decide() picks the same sector as laya.choose_sector() on all 243 cases."""
    assert len(_GOLD) == 243
    nlp = FinancialNLP()
    mismatches: list[tuple[str, str, str]] = []
    for case in _GOLD:
        subject = case["subject"]
        view = laya.classify(subject, "")
        keyword = nlp.analyze(subject, "").sector
        tickers = resolve_company_tickers(subject)
        want = laya.choose_sector("", view, keyword, tickers=tickers)
        got = decide("", view, keyword, tickers=tickers)["sector"]
        if got != want:
            mismatches.append((subject, want, got))
    assert not mismatches, mismatches


def test_confident_laya_view_without_tickers_is_attributed_to_laya() -> None:
    out = decide("", LayaView("energy", 0.95, "", 0.0), "")
    assert out["decided_by"] == "laya"
    assert out["sector"] == "energy"


def test_low_confidence_laya_and_a_cleared_llm_fall_back_to_other() -> None:
    out = decide("technology", LayaView("financials", 0.2, "", 0.0), "")
    assert out["decided_by"] == "fallback"
    assert out["decided_by"] != "model"
    assert out["sector"] == "other"


def test_supported_llm_label_is_attributed_to_model() -> None:
    out = decide("energy", None, "energy")
    assert out["decided_by"] == "model"
    assert out["sector"] == "energy"


def test_llm_technology_with_company_support_is_attributed_to_model() -> None:
    out = decide("technology", None, "", tickers=["AMD"])
    assert out["decided_by"] == "model"
    assert out["sector"] == "technology"


def test_company_evidence_alone_is_attributed_to_company() -> None:
    out = decide("", None, "", tickers=["XOM", "CVX", "XOM"])
    assert out["decided_by"] == "company"
    assert out["sector"] == "energy"


def test_keyword_evidence_alone_is_attributed_to_keyword() -> None:
    out = decide("", LayaView("technology", 0.2, "", 0.0), "financials")
    assert out["decided_by"] == "keyword"
    assert out["sector"] == "financials"


def test_a_named_company_outranks_a_confident_laya_view() -> None:
    out = decide("", LayaView("technology", 0.9, "", 0.0), "", tickers=["NFLX"])
    assert out["decided_by"] != "laya"
    assert out["decided_by"] == "company"
    assert out["sector"] == "communications"


def test_per_source_report(request) -> None:
    """Every source is scored; the table is shown under plain `pytest -q`."""
    lines = _build_report()
    if not request.config.pluginmanager.has_plugin("sector-chain-report"):
        request.config.pluginmanager.register(
            _TerminalReport(lines), "sector-chain-report"
        )
    print("\n".join(lines))

    stats = _measure()
    assert stats.n == len(_GOLD) == 243
    assert stats.parity == stats.n
    assert sum(stats.attributed.values()) == stats.n
    assert stats.attributed["model"] == 0
    assert set(stats.attributed) <= set(DECIDERS)

    decided = {line.split()[1] for line in lines if line.startswith("decided_by ")}
    assert decided == set(DECIDERS)
    assert lines[0].startswith("Sector chain on the gold set: 243 cases, llm_sector=")
    assert lines[1] == "parity: decide()==laya.choose_sector() on 243/243 cases"
    assert any("UNPROVABLE offline" in line for line in lines)
    assert not any(
        line.startswith("decided_by model") and "%" in line for line in lines
    )
