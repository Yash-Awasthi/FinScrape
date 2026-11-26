"""Precision/recall for the scenario clusterer against 20 clusters labelled in-repo.

Corpus: `tests/gold/sector_set.jsonl`, the frozen 243-headline gold set (ids 1-56
model-choice 2026-09-29, ids 57-243 production subjects 2026-06..09). The 20
cluster labels below were written in-repo on 2026-11-26 from the headline text;
each carries its provenance and rationale. They describe the headlines, not the
clustering output. Rubric: `docs/EVAL.md`, "Scenario clustering: precision/recall".

Measured path: `finscrape.analysis.clusters.cluster_events` with `same_story`'s
word rule (two shared content words, at least half the shorter headline) as the
similarity, at `LEXICAL_OVERLAP`. The shared-ticker gate is removed because no
gold headline carries a ticker. The Ollama embedding path is UNPROVABLE offline:
no model and no recorded vectors are committed.
"""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

from finscrape.analysis import clusters

CORPUS = Path(__file__).parent / "gold" / "sector_set.jsonl"

# One entry per cluster: the corpus ids it covers, plus the provenance and the
# rationale that make those headlines one storyline rather than one topic.
CLUSTERS = (
    {
        "name": "ebola_drc",
        "ids": (33, 180, 198, 209, 216),
        "provenance": "sector_set ids 33, 180, 198, 209, 216",
        "rationale": (
            "One outbreak: a vaccine trial starting, responders fighting a widening "
            "epidemic, deaths passing 2,000 and the toll on women and girls are reports "
            "on the same DRC Ebola story."
        ),
    },
    {
        "name": "hormuz_crisis",
        "ids": (1, 80, 158, 186, 190),
        "provenance": "sector_set ids 1, 80, 158, 186, 190",
        "rationale": (
            "The same Strait of Hormuz shipping crisis: the closure, Iran-Oman talks, "
            "ships struck and Asia rewriting its oil and gas strategy."
        ),
    },
    {
        "name": "ukraine_drones_russian_energy",
        "ids": (48, 189, 238),
        "provenance": "sector_set ids 48, 189, 238",
        "rationale": (
            "One Ukrainian drone campaign against Russian energy infrastructure: "
            "refinery strikes in Samara and Bashkortostan, the Afipsky refinery hit and "
            "the power-grid strikes."
        ),
    },
    {
        "name": "fed_rate_hike",
        "ids": (6, 13, 20, 179),
        "provenance": "sector_set ids 6, 13, 20, 179",
        "rationale": (
            "The same Fed tightening call: pressure on Warsh, a strong jobs report "
            "reviving hike fears, the decision itself and its trading read-through."
        ),
    },
    {
        "name": "ai_risk_and_regulation",
        "ids": (35, 92, 108, 123),
        "provenance": "sector_set ids 35, 92, 108, 123",
        "rationale": (
            "One policy thread: a UN panel, a lab researcher, a US president and a UN "
            "rights chief all speaking to AI risk and the case for stronger safeguards."
        ),
    },
    {
        "name": "uk_power_plant_cyber",
        "ids": (194, 196),
        "provenance": "sector_set ids 194, 196",
        "rationale": (
            "The same UK power-plant cyber incident, first reported as an Iran-linked "
            "attack and then as a cyber attack that shut the plant down."
        ),
    },
    {
        "name": "us_housing_law",
        "ids": (232, 233),
        "provenance": "sector_set ids 232, 233",
        "rationale": (
            "The same US housing-affordability law moving from a bill that boosts "
            "affordability to a reform that becomes law."
        ),
    },
    {
        "name": "houthi_saudi_strikes",
        "ids": (55, 71),
        "provenance": "sector_set ids 55, 71",
        "rationale": (
            "The same Houthi missile and drone wave against Saudi cities, reported once "
            "with the Yemen displacement fallout and once by the Saudi-led coalition."
        ),
    },
    {
        "name": "us_drug_boat_strikes",
        "ids": (56, 64, 84),
        "provenance": "sector_set ids 56, 64, 84",
        "rationale": (
            "The US campaign against alleged drug boats: the policy, the widening "
            "strikes and arrests, and a named casualty report from the eastern Pacific."
        ),
    },
    {
        "name": "israeli_strikes_gaza",
        "ids": (46, 110),
        "provenance": "sector_set ids 46, 110",
        "rationale": (
            "Israeli strikes killing civilians in Gaza, reported as two casualty "
            "accounts from the same air campaign."
        ),
    },
    {
        "name": "crude_oil_slide",
        "ids": (93, 138),
        "provenance": "sector_set ids 93, 138",
        "rationale": (
            "The same crude-price slide, first on US prices extending losses and then "
            "on Middle East diplomatic hopes pressuring oil."
        ),
    },
    {
        "name": "canada_us_trade_war",
        "ids": (132, 142),
        "provenance": "sector_set ids 132, 142",
        "rationale": (
            "Canada's response to the fresh US tariffs: Carney calling them a "
            "miscalculation and the trade war showing up in consumer prices."
        ),
    },
    {
        "name": "us_mortgage_rates",
        "ids": (206, 217),
        "provenance": "sector_set ids 206, 217",
        "rationale": (
            "The US mortgage-rate turn: brokers calling the end of rate cuts and the "
            "rate climbing to a near one-year high."
        ),
    },
    {
        "name": "venezuela_oil_opening",
        "ids": (63, 96, 128),
        "provenance": "sector_set ids 63, 96, 128",
        "rationale": (
            "The US-Venezuela oil opening: the claim of partial control over the "
            "reserves, the energy deals that followed and the fact-check on prices."
        ),
    },
    {
        "name": "us_china_tariffs",
        "ids": (23, 107),
        "provenance": "sector_set ids 23, 107",
        "rationale": (
            "US tariff policy toward China: the standing policy and the mutual "
            "reduction of tariffs on goods."
        ),
    },
    {
        "name": "ai_datacentre_power",
        "ids": (160, 201),
        "provenance": "sector_set ids 160, 201",
        "rationale": (
            "AI datacentres as an electricity problem: local political opposition and "
            "the warning that their load threatens power systems."
        ),
    },
    {
        "name": "russian_strikes_ukraine",
        "ids": (87, 126, 185),
        "provenance": "sector_set ids 87, 126, 185",
        "rationale": (
            "Russian strikes on Ukrainian cities: the daytime attack on Kyiv, the mall "
            "wreckage and the homes damaged in one campaign."
        ),
    },
    {
        "name": "homeowners_insurance",
        "ids": (141, 195),
        "provenance": "sector_set ids 141, 195",
        "rationale": (
            "The US homeowners-insurance crisis: a politician attacking the system and "
            "a state where hail is shrinking what insurers will cover."
        ),
    },
    {
        "name": "iran_sanctions_pressure",
        "ids": (174, 192),
        "provenance": "sector_set ids 174, 192",
        "rationale": (
            "US sanctions pressure on Iran: a Turkish bank designated to squeeze Iran "
            "and the rial hitting a record low before more sanctions."
        ),
    },
    {
        "name": "gaza_food_aid",
        "ids": (120, 156),
        "provenance": "sector_set ids 120, 156",
        "rationale": (
            "Gaza food aid: convoys reaching families in severe food insecurity and "
            "the WFP halving West Bank assistance with Gaza cuts looming."
        ),
    },
)


def _corpus() -> list[dict]:
    return [
        json.loads(line)
        for line in CORPUS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _events(rows: list[dict]) -> list[dict]:
    return [
        {
            "id": row["id"],
            "subject": row["subject"],
            "tickers": [],
            "sources": [],
            "signal_score": 0,
            "created_at": None,
        }
        for row in rows
    ]


def _word_rule(a: str, b: str) -> float:
    """`same_story`'s word rule without its shared-ticker gate."""
    wa, wb = clusters.subject_words(a), clusters.subject_words(b)
    if not wa or not wb:
        return 0.0
    shared = len(wa & wb)
    if shared < 2:
        return 0.0
    return shared / min(len(wa), len(wb))


def _measure() -> tuple[float, float, int, int, int, list[dict]]:
    rows = _corpus()
    metas = clusters.cluster_events(
        _events(rows), _word_rule, threshold=clusters.LEXICAL_OVERLAP
    )
    owner = {mid: idx for idx, meta in enumerate(metas) for mid in meta["member_ids"]}
    gold_pairs = {
        tuple(sorted(pair))
        for cluster in CLUSTERS
        for pair in combinations(cluster["ids"], 2)
    }
    ids = [row["id"] for row in rows]
    tp = fp = fn = 0
    for a, b in combinations(ids, 2):
        same_pred = owner[a] == owner[b]
        same_gold = (a, b) in gold_pairs
        if same_pred and same_gold:
            tp += 1
        elif same_pred:
            fp += 1
        elif same_gold:
            fn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return precision, recall, tp, fp, fn, metas


def test_corpus_is_the_frozen_gold_set():
    rows = _corpus()
    assert len(rows) == 243
    assert len({row["id"] for row in rows}) == 243


def test_twenty_clusters_are_well_formed():
    ids = {row["id"] for row in _corpus()}
    seen: set[int] = set()
    assert len(CLUSTERS) == 20
    for cluster in CLUSTERS:
        assert len(cluster["ids"]) >= 2
        assert len(set(cluster["ids"])) == len(cluster["ids"])
        assert set(cluster["ids"]) <= ids
        assert cluster["provenance"].strip()
        assert cluster["rationale"].strip()
        assert not seen & set(cluster["ids"])
        seen |= set(cluster["ids"])
    assert sum(len(c["ids"]) * (len(c["ids"]) - 1) // 2 for c in CLUSTERS) == 56


def test_precision_and_recall_match_the_published_number():
    precision, recall, tp, fp, fn, metas = _measure()
    assert (tp, fp, fn) == (18, 7, 38)
    assert round(precision, 3) == 0.720
    assert round(recall, 3) == 0.321
    # 20 labelled storylines cannot collapse the 243-headline corpus into one cluster.
    assert len(metas) == 225
    assert sum(1 for meta in metas if meta["size"] == 1) == 211
