"""Daily Laya refresh: harvest new headlines, have Claude label the ones Laya is unsure
of, LoRA-train a candidate, and promote it only if it beats the current model.

    .venv/Scripts/python scripts/laya_train/daily.py [--dry-run]

Runs in the project venv (Postgres, feeds, CPU Laya for scoring); training runs in
the CUDA venv under LAYA_FT_HOME (default ~/laya-ft). State lives there too:
  data/train.json    labelled training cases (seeded from sector_train.json)
  data/holdout.json  a fifth of each day's labels, never trained on
  stage1/            the full fine-tune on public data, if built; LoRA starts from it
  current/           the promoted model; .env points FINSCRAPE_LAYA_MODEL here
  history.jsonl      one line per run with both scores
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values  # noqa: E402

from finscrape.analysis import laya  # noqa: E402
from finscrape.analysis.nlp import FinancialNLP  # noqa: E402
from finscrape.analysis.sectors import TAXONOMY  # noqa: E402
from finscrape.analysis.ticker_map import resolve_company_tickers  # noqa: E402

HOME = Path(os.environ.get("LAYA_FT_HOME", Path.home() / "laya-ft"))
DATA, CURRENT, RUNS = HOME / "data", HOME / "current", HOME / "runs"
GOLD = ROOT / "tests" / "fixtures" / "sector_gold.json"
MAX_LABELS = 150
BATCH = 50
MIN_GAIN = 2  # more test cases right than the current model
MOVE_REPEAT = 3
DIRECTION_SLACK = 0.02  # balanced recall a sector gain may cost

PROMPT = """You label news headlines for a market-sector classifier.
For each headline in the JSON object on stdin (id -> headline), pick the one sector whose revenues or
costs the news moves most:
{criteria}
- other: no sector clearly affected (domestic politics, crime, sport, disasters with
  no market angle, diplomacy with no named industry).
House rules: crypto counts as financials; airlines, defence, ship orders and freight as
industrials; central banks, rates and sanctions on finance as financials; attacks on oil
infrastructure or shipping lanes for crude as energy. War, terror plots, troop moves and
generic sanctions with no named industry are other, as is personal finance advice.
Also give the direction the news pushes the affected prices: positive, negative or neutral
(neutral for other).
Reply with only a JSON object mapping each id to "sector,direction"."""

# Price alerts and quake reports arrive by the hundred with one shape; a few teach Laya
# everything they can.
TEMPLATED = re.compile(
    r"\b(surged|dropped) [+-]?[\d.]+%? in 24h$|^m ?[\d.]+ earthquake", re.IGNORECASE
)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", s.lower())).strip()


def parse_label(raw: object) -> tuple[str, str]:
    """("sector", "direction") from a "sector,direction" reply; unknown parts come back empty."""
    sector, _, direction = str(raw).partition(",")
    sector, direction = sector.strip().lower(), direction.strip().lower()
    return (
        sector if sector in TAXONOMY else "",
        direction if direction in ("positive", "negative", "neutral") else "",
    )


def load(path: Path) -> list[dict]:
    return json.loads(path.read_text("utf-8"))["cases"] if path.exists() else []


def dump(path: Path, cases: list[dict]) -> None:
    path.write_text(json.dumps({"cases": cases}, ensure_ascii=False, indent=1), "utf-8")


async def recent_subjects() -> list[str]:
    import asyncpg

    conn = await asyncpg.connect(dotenv_values(ROOT / ".env")["WORLDFIN_DATABASE_URL"])
    try:
        rows = await conn.fetch(
            "SELECT subject FROM events WHERE created_at >= now() - interval '3 days'"
        )
    finally:
        await conn.close()
    return [r["subject"] for r in rows]


def harvest(known: set[str]) -> list[str]:
    from finscrape.scrapers.world import WorldRSSScraper

    titles = asyncio.run(recent_subjects())
    titles += [a.title for a in WorldRSSScraper(max_age_hours=48).collect()]
    out, seen = [], set(known)
    for t in titles:
        n = norm(t)
        if len(n) >= 15 and n not in seen and not TEMPLATED.search(t.strip()):
            seen.add(n)
            out.append(re.sub(r"\s+", " ", t).strip())
    return out


def use_model(path: Path | None) -> None:
    """Point finscrape.analysis.laya at a checkpoint (None = the stock model)."""
    from laya import Agent, Router

    laya._predict = Agent(str(path)).predict if path else Router().predict
    laya._unavailable = False
    laya._stamp = None


def pick_unsure(headlines: list[str]) -> list[str]:
    scored = []
    for h in headlines:
        view = laya.classify(h, "")
        scored.append((view.sector_p if view else 0.0, h))
    scored.sort()
    return [h for _, h in scored[:MAX_LABELS]]


def claude_labels(headlines: list[str]) -> list[dict]:
    exe = shutil.which("claude")
    if not exe:
        raise SystemExit("claude CLI not on PATH")
    criteria = "\n".join(f"- {k}: {v}" for k, v in laya._SECTOR_CRITERIA.items())
    cases = []
    for i in range(0, len(headlines), BATCH):
        chunk = headlines[i : i + BATCH]
        run = subprocess.run(
            [exe, "-p", PROMPT.format(criteria=criteria)],
            input=json.dumps(dict(enumerate(chunk)), ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=600,
        )
        match = re.search(r"\{.*\}", run.stdout, re.S)
        try:
            labels = json.loads(match.group(0)) if match else {}
        except json.JSONDecodeError:
            labels = {}
        for j, h in enumerate(chunk):
            sector, direction = parse_label(labels.get(str(j), ""))
            if sector:
                case = {"subject": h, "sector": sector, "source": "claude"}
                cases.append(case | ({"direction": direction} if direction else {}))
    return cases


def balanced_recall(pairs: list[tuple[str, str]]) -> float:
    """Mean per-class recall over (truth, prediction) pairs. Three in four labels are
    neutral, so plain hit counts reward a model that never calls a move."""
    classes = {t for t, _ in pairs}
    if not classes:
        return 0.0
    return sum(
        sum(g == t for tt, g in pairs if tt == t) / sum(tt == t for tt, _ in pairs)
        for t in classes
    ) / len(classes)


def hits(cases: list[dict]) -> tuple[int, float]:
    """Sector hits through the production chain, and balanced direction recall on the
    cases that carry a direction label."""
    nlp = FinancialNLP()
    sector = 0
    pairs = []
    for c in cases:
        s = c["subject"]
        view = laya.classify(s, "")
        got = laya.choose_sector(
            "",
            view,
            nlp.analyze(s, "").sector,
            tickers=resolve_company_tickers(s),
        )
        sector += got == c["sector"]
        if c.get("direction"):
            pairs.append((c["direction"], view.direction if view else ""))
    return sector, balanced_recall(pairs)


def accuracy(cases: list[dict]) -> float:
    return hits(cases)[0] / len(cases)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="harvest and label only")
    args = ap.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    train_path, holdout_path = DATA / "train.json", DATA / "holdout.json"
    if not train_path.exists():
        shutil.copy(HERE / "sector_train.json", train_path)
    train, holdout, gold = load(train_path), load(holdout_path), load(GOLD)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    incumbent = CURRENT if CURRENT.exists() else None

    known = {norm(c["subject"]) for c in train + holdout + gold}
    fresh = harvest(known)
    use_model(incumbent)
    unsure = pick_unsure(fresh)
    labelled = claude_labels(unsure)
    print(
        f"{len(fresh)} new headlines, {len(unsure)} unsure, {len(labelled)} labelled",
        flush=True,
    )
    random.Random(stamp).shuffle(labelled)
    holdout += labelled[::5]
    train += [c for i, c in enumerate(labelled) if i % 5]
    dump(train_path, train)
    dump(holdout_path, holdout)
    if args.dry_run:
        return

    # Three in four direction labels are neutral; repeating the moves keeps the LoRA
    # from learning to never call one (balanced recall 0.58 plain, 0.65 at x3).
    weighted = DATA / "train-weighted.json"
    moves = [c for c in train if c.get("direction") in ("positive", "negative")]
    dump(weighted, train + moves * (MOVE_REPEAT - 1))

    candidate = RUNS / stamp
    base = ["--base", str(HOME / "stage1")] if (HOME / "stage1").exists() else []
    subprocess.run(
        [
            str(HOME / ".venv" / "Scripts" / "python.exe"),
            "-u",
            str(HERE / "train.py"),
            str(candidate),
            "--data",
            str(weighted),
            "--mode",
            "lora",
            "--epochs",
            "3",
            *base,
        ],
        check=True,
        env={**os.environ, "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"},
    )
    for epoch_dir in candidate.glob("epoch*"):
        shutil.rmtree(epoch_dir)

    test = gold + holdout
    old, old_dir = hits(test)
    use_model(candidate)
    new, new_dir = hits(test)
    # One headline either way is noise; a sector gain may not cost direction.
    promoted = new - old >= MIN_GAIN and new_dir >= old_dir - DIRECTION_SLACK
    if promoted:
        shutil.rmtree(CURRENT, ignore_errors=True)
        shutil.move(str(candidate), str(CURRENT))
        env = ROOT / ".env"
        if "FINSCRAPE_LAYA_MODEL" not in env.read_text("utf-8"):
            with env.open("a", encoding="utf-8") as f:
                f.write(f"\nFINSCRAPE_LAYA_MODEL={CURRENT}\n")
        from publish import publish

        try:
            print("published", publish(CURRENT), flush=True)
        except (subprocess.CalledProcessError, OSError) as exc:
            print("publish failed; ingest keeps the previous checkpoint:", exc)
    else:
        shutil.rmtree(candidate, ignore_errors=True)
    line = {
        "date": stamp,
        "labelled": len(labelled),
        "test_cases": len(test),
        "incumbent": round(old / len(test), 4),
        "candidate": round(new / len(test), 4),
        "direction_cases": sum(bool(c.get("direction")) for c in test),
        "incumbent_direction": round(old_dir, 4),
        "candidate_direction": round(new_dir, 4),
        "promoted": promoted,
    }
    with (HOME / "history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")
    print(line)


if __name__ == "__main__":
    main()
