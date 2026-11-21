"""Evaluate a model (or a recorded run) on the frozen gold set.

    python -m scripts.eval_model --model mimo-v2.6-flash:free --prompt v1     # live
    python -m scripts.eval_model --replay tests/gold/recordings/x.jsonl --gate  # offline

What it prints, per plan M2.1:

* **JSON validity** — share of replies that parse and satisfy `reply_schema.ModelReply`,
  which is the only thing the pipeline can use.
* **Sector accuracy** — the reply's sector against the gold sector.
* **Verdict agreement** — the reply's verdict against the labelled cases (1–56).
* **p50 / p90 latency** — measured per call, or replayed from the recording.

`--gate` compares the run against the baseline stored in `docs/EVAL.md` for the same
model and prompt and exits non-zero when sector accuracy drops by more than
`MAX_SECTOR_DROP`. A model switch that silently halves accuracy cannot pass.

`--replay` needs no network: the recording carries each reply, its latency and a
fingerprint of the exact prompt that produced it, so editing a prompt without
re-recording fails the run instead of quietly measuring the old text.

    python -m scripts.eval_model --model X --record tests/gold/recordings/X.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "tests" / "gold" / "sector_set.jsonl"
EVAL_DOC = ROOT / "docs" / "EVAL.md"

# A model switch may cost this much sector accuracy before it is refused (plan M2.1).
MAX_SECTOR_DROP = 0.05

SECTORS = (
    "energy",
    "technology",
    "financials",
    "industrials",
    "materials",
    "healthcare",
    "consumer",
    "utilities",
    "real_estate",
    "communications",
    "other",
)
_SECTOR_SYNONYMS = {
    "tech": "technology",
    "information_technology": "technology",
    "it": "technology",
    "finance": "financials",
    "financial": "financials",
    "banking": "financials",
    "health": "healthcare",
    "health_care": "healthcare",
    "consumer_goods": "consumer",
    "retail": "consumer",
    "realestate": "real_estate",
    "real-estate": "real_estate",
    "telecom": "communications",
    "media": "communications",
    "defence": "industrials",
    "defense": "industrials",
    "industrial": "industrials",
    "material": "materials",
    "utility": "utilities",
}

VERDICTS = ("INVEST", "PULL_OUT", "OBSERVE", "CAUTIOUS")

# A pseudo-model: the in-tree deterministic layer stack (keyword/Laya sector chain +
# the rule-based analyst for direction), recorded once so CI can score the whole eval
# path with no network and no credentials. It is the baseline the gate compares
# against, not a model under consideration.
PSEUDO_MODELS = {"keyword-baseline": "keyword"}


def _verdict_from_score(reply: dict[str, Any]) -> str:
    """The product's thresholds, for a reply that carries a score but no verdict.

    Live models answer with a verdict; the deterministic analyst answers with a score,
    and the pipeline turns that into a verdict with exactly these bands (INVEST +3,
    OBSERVE 0..+2, CAUTIOUS -1..-2, PULL_OUT -3).
    """
    score = int(reply.get("signal_score") or 0)
    if score >= 3:
        return "INVEST"
    if score <= -3:
        return "PULL_OUT"
    if score <= -1:
        return "CAUTIOUS"
    return "OBSERVE"


@dataclass
class Case:
    id: int
    subject: str
    sector: str
    verdict: str | None
    reason: str
    provenance: str


@dataclass
class Result:
    case: Case
    reply: dict[str, Any] | None
    ms: float
    error: str = ""


@dataclass
class Metrics:
    model: str = ""
    prompt_variant: str = ""
    cases: int = 0
    valid: int = 0
    sector_hits: int = 0
    verdict_scored: int = 0
    verdict_hits: int = 0
    latencies: list[float] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    # Set when gating a stored run, where only the rate survives (not the per-case rows).
    sector_override: float | None = None

    @property
    def json_validity(self) -> float:
        return self.valid / self.cases if self.cases else 0.0

    @property
    def sector_accuracy(self) -> float:
        if self.sector_override is not None:
            return self.sector_override
        return self.sector_hits / self.cases if self.cases else 0.0

    @property
    def verdict_agreement(self) -> float:
        return self.verdict_hits / self.verdict_scored if self.verdict_scored else 0.0

    @property
    def p50(self) -> float:
        return statistics.median(self.latencies) if self.latencies else 0.0

    @property
    def p90(self) -> float:
        if not self.latencies:
            return 0.0
        ordered = sorted(self.latencies)
        index = min(len(ordered) - 1, round(0.9 * (len(ordered) - 1)))
        return ordered[index]

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "prompt": self.prompt_variant,
            "cases": self.cases,
            "json_validity": round(self.json_validity, 4),
            "sector_accuracy": round(self.sector_accuracy, 4),
            "verdict_agreement": round(self.verdict_agreement, 4),
            "verdict_cases": self.verdict_scored,
            "p50_ms": round(self.p50, 1),
            "p90_ms": round(self.p90, 1),
            "failures": self.failures[:10],
        }


def load_gold(path: Path = GOLD) -> list[Case]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        cases.append(
            Case(
                id=row["id"],
                subject=row["subject"],
                sector=row["sector"],
                verdict=row.get("verdict"),
                reason=row.get("reason", ""),
                provenance=row.get("provenance", ""),
            )
        )
    return cases


def normalise_sector(value: str | None) -> str:
    """Free text → one of the eleven. The model writes prose here, so be forgiving."""
    text = (value or "").strip().lower()
    if not text:
        return "other"
    text = re.sub(r"[^a-z0-9_ -]+", " ", text)
    for sector in SECTORS:
        if re.search(rf"\b{re.escape(sector)}\b", text):
            return sector
        spaced = sector.replace("_", " ")
        if re.search(rf"\b{re.escape(spaced)}\b", text):
            return sector
    for word, sector in _SECTOR_SYNONYMS.items():
        if re.search(rf"\b{re.escape(word)}\b", text.replace("-", "_")):
            return sector
    return "other"


def normalise_verdict(value: str | None) -> str:
    text = (value or "").strip().upper()
    return text if text in VERDICTS else "OBSERVE"


def prompt_fingerprint(system: str, analysis: str) -> str:
    return hashlib.sha256((system + "\x00" + analysis).encode("utf-8")).hexdigest()[:16]


def _render(case: Case, variant: str) -> tuple[str, str, str]:
    from finscrape.analysis.prompt_registry import get_prompts
    from finscrape.analysis.prompts import render_prompt

    system, analysis = get_prompts(variant)
    return system, analysis, render_prompt(analysis, case.subject, "")


def score(
    case: Case, reply: dict[str, Any] | None, ms: float, error: str = ""
) -> Result:
    return Result(case=case, reply=reply, ms=ms, error=error)


def measure(results: list[Result], model: str, variant: str) -> Metrics:
    from finscrape.analysis.reply_schema import reply_errors

    m = Metrics(model=model, prompt_variant=variant, cases=len(results))
    for r in results:
        m.latencies.append(r.ms)
        if r.reply is None:
            m.failures.append(f"#{r.case.id} no reply {r.error}".strip())
            continue
        errors = reply_errors(r.reply)
        if errors:
            m.failures.append(f"#{r.case.id} invalid: {'; '.join(errors)[:120]}")
            continue
        m.valid += 1
        if normalise_sector(r.reply.get("sector_impact")) == r.case.sector:
            m.sector_hits += 1
        if r.case.verdict:
            m.verdict_scored += 1
            answered = r.reply.get("verdict") or _verdict_from_score(r.reply)
            if normalise_verdict(answered) == r.case.verdict:
                m.verdict_hits += 1
    return m


def run_live(cases: list[Case], model: str, variant: str) -> list[Result]:
    out = []
    for case in cases:
        system, _, prompt = _render(case, variant)
        started = time.perf_counter()
        if model in PSEUDO_MODELS:
            reply = _run_pseudo(case, variant)
        else:
            from finscrape.analysis.ai_client import call_ai

            reply = call_ai(prompt, system, model=model)
        elapsed = (time.perf_counter() - started) * 1000
        out.append(
            score(case, reply, elapsed, "" if reply else "model returned nothing")
        )
    return out


def _run_pseudo(case: Case, variant: str) -> dict[str, Any] | None:
    """The deterministic layer stack, answering in the same shape a model does.

    Sector comes from the real chain (`choose_sector`: Laya view → keyword → company
    map), direction from the rule-based analyst. This is the floor a model has to beat,
    and the thing the offline gate measures with no network.
    """
    from finscrape.analysis import laya
    from finscrape.analysis.fallback import analyze_without_llm
    from finscrape.analysis.nlp import FinancialNLP
    from finscrape.analysis.ticker_map import resolve_company_tickers

    nlp = FinancialNLP()
    nlp_result = nlp.analyze(case.subject, "")
    sector = laya.choose_sector(
        "", None, nlp_result.sector, tickers=resolve_company_tickers(case.subject)
    )
    reply = analyze_without_llm(case.subject, "", nlp_result)
    if reply is None:
        return {
            "relevant": True,
            "signal_score": 0,
            "sector_impact": sector,
            "verdict": "OBSERVE",
            "confidence": 0.3,
            "reasoning": "no rule fired; the sector chain alone answered",
        }
    reply["sector_impact"] = sector
    return reply


def record(results: list[Result], path: Path, model: str, variant: str) -> None:
    """Write a replay file. The prompt fingerprint makes a stale recording detectable."""
    system, analysis = _prompt_pair(variant)
    header = {
        "kind": "eval-recording",
        "model": model,
        "prompt": variant,
        "prompt_fingerprint": prompt_fingerprint(system, analysis),
        "recorded": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    lines = [json.dumps(header)]
    for r in results:
        lines.append(
            json.dumps(
                {
                    "id": r.case.id,
                    "ms": round(r.ms, 1),
                    "reply": r.reply,
                    "error": r.error,
                }
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _prompt_pair(variant: str) -> tuple[str, str]:
    from finscrape.analysis.prompt_registry import get_prompts

    return get_prompts(variant)


def run_replay(cases: list[Case], path: Path, variant: str) -> tuple[list[Result], str]:
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    header = json.loads(lines[0])
    if header.get("kind") != "eval-recording":
        raise SystemExit(f"{path}: not an eval recording")
    variant = header.get("prompt", variant)
    system, analysis = _prompt_pair(variant)
    expected = prompt_fingerprint(system, analysis)
    if header.get("prompt_fingerprint") != expected:
        raise SystemExit(
            f"stale recording: {path} was made with prompt {header.get('prompt_fingerprint')!r} "
            f"but the prompt now hashes to {expected!r}. Re-record with --record, and review the "
            "diff before you commit it."
        )
    by_id = {json.loads(ln)["id"]: json.loads(ln) for ln in lines[1:]}
    results = []
    for case in cases:
        row = by_id.get(case.id)
        if row is None:
            results.append(score(case, None, 0.0, "missing from the recording"))
            continue
        results.append(
            score(
                case, row.get("reply"), float(row.get("ms") or 0), row.get("error", "")
            )
        )
    return results, header.get("model", "recorded")


def baseline_for(model: str, variant: str, doc: Path | None = None) -> float | None:
    """Sector accuracy of the newest stored run for this model + prompt, if any."""
    doc = doc or EVAL_DOC
    if not doc.is_file():
        return None
    rows = [
        ln
        for ln in doc.read_text(encoding="utf-8").splitlines()
        if ln.startswith("| ") and "model" not in ln.lower() and "---" not in ln
    ]
    for line in reversed(rows):
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        if cells[0].strip("`") == model and cells[1].strip("`") == variant:
            match = re.search(r"([\d.]+)%", cells[3])
            if match:
                return float(match.group(1)) / 100
    return None


def append_doc(m: Metrics, doc: Path | None = None) -> None:
    """Append one run row to docs/EVAL.md (the run history, newest last)."""
    doc = doc or EVAL_DOC
    stamp = time.strftime("%Y-%m-%d", time.gmtime())
    row = (
        f"| {m.model} | {m.prompt_variant} | {stamp} | {m.sector_accuracy:.1%} | "
        f"{m.json_validity:.1%} | {m.verdict_agreement:.1%} ({m.verdict_scored}) | "
        f"{m.p50:.0f} / {m.p90:.0f} ms |\n"
    )
    text = (
        doc.read_text(encoding="utf-8")
        if doc.is_file()
        else "# Model evaluation runs\n\n"
    )
    doc.write_text(text + row, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--model", default=os.getenv("FINSCRAPE_MODEL", ""), help="model id to measure"
    )
    parser.add_argument(
        "--prompt", default="v1", help="prompt variant from prompt_registry"
    )
    parser.add_argument("--limit", type=int, default=0, help="only the first N cases")
    parser.add_argument(
        "--replay", default="", help="recorded run to score instead of calling a model"
    )
    parser.add_argument("--record", default="", help="write a replay file for this run")
    parser.add_argument(
        "--gate", action="store_true", help="fail on a >5 point sector drop"
    )
    parser.add_argument(
        "--append-docs", action="store_true", help="append the run to docs/EVAL.md"
    )
    parser.add_argument("--json", default="", help="write the metrics as JSON here")
    parser.add_argument(
        "--from-json", default="", help="gate a stored --json result instead of running"
    )
    args = parser.parse_args(argv)

    if args.from_json:
        return _gate_stored(Path(args.from_json))

    cases = load_gold()
    if args.limit:
        cases = cases[: args.limit]

    if args.replay:
        results, model = run_replay(cases, Path(args.replay), args.prompt)
    else:
        if not args.model:
            parser.error("--model is required unless --replay is given")
        model = args.model
        results = run_live(cases, args.model, args.prompt)
        if args.record:
            record(results, Path(args.record), model, args.prompt)

    m = measure(results, model, args.prompt)
    print(f"model           {m.model}")
    print(f"prompt          {m.prompt_variant}")
    print(f"cases           {m.cases}")
    print(f"JSON validity   {m.json_validity:.1%}")
    print(f"sector accuracy {m.sector_accuracy:.1%}")
    print(f"verdict agree   {m.verdict_agreement:.1%} of {m.verdict_scored} labelled")
    print(f"latency         p50 {m.p50:.0f} ms · p90 {m.p90:.0f} ms")
    for failure in m.failures[:10]:
        print(f"  ! {failure}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(m.as_dict(), indent=2) + "\n", encoding="utf-8"
        )
    if args.append_docs:
        append_doc(m)

    if args.gate:
        return gate(m)
    return 0


def gate(m: Metrics) -> int:
    """Refuse a run that costs more than MAX_SECTOR_DROP against its stored baseline."""
    baseline = baseline_for(m.model, m.prompt_variant)
    if baseline is None:
        print(
            f"gate: no baseline for {m.model} / {m.prompt_variant} in docs/EVAL.md — recorded"
        )
        return 0
    drop = baseline - m.sector_accuracy
    print(
        f"gate: baseline {baseline:.1%}, now {m.sector_accuracy:.1%}, drop {drop:+.1%}"
    )
    if drop > MAX_SECTOR_DROP:
        print(f"gate: FAIL — sector accuracy fell more than {MAX_SECTOR_DROP:.0%}")
        return 1
    return 0


def _gate_stored(path: Path) -> int:
    """Gate a run that was measured elsewhere (the weekly live workflow)."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    m = Metrics(
        model=payload.get("model", ""),
        prompt_variant=payload.get("prompt", "v1"),
        cases=int(payload.get("cases", 0)),
    )
    m.sector_override = float(payload.get("sector_accuracy", 0.0))
    print(f"gate: stored run {m.model} / {m.prompt_variant}")
    return gate(m)


if __name__ == "__main__":
    sys.exit(main())
