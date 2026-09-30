"""Laya typed-decision classifier for sector and direction.

Laya (convaiinnovations/laya) answers constrained questions — pick one of N
labels — with calibrated probabilities from one encoder pass, no generation.
That is the shape of `sector_impact` and `impact_direction`, which the analysis
LLM gets wrong often enough to matter (blank or "technology" on political stories).

Two runtimes, same model and question schema:
- `laya_mlx` (aac6fef/laya-mlx) on Apple Silicon, where MLX runs natively.
- `laya` (PyTorch) everywhere else, including Windows.

Opt-in by install: with neither package present every call returns None and the
pipeline keeps its LLM/keyword behaviour. FINSCRAPE_LAYA=0 disables it outright.
"""

from __future__ import annotations

import logging
import os
import platform
import sys
import threading
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from finscrape.analysis.sectors import TAXONOMY, normalize
from finscrape.analysis.ticker_map import TICKER_SECTOR

logger = logging.getLogger(__name__)

_MLX_REPO = os.environ.get("FINSCRAPE_LAYA_MLX_MODEL", "aac6fef/laya-mlx")
# A local fine-tuned checkpoint (scripts/laya_train); unset uses the router's default.
_MODEL = os.environ.get("FINSCRAPE_LAYA_MODEL", "")
_MAX_CHARS = 2000  # headline + lede carry the decision; bodies only add latency

# Below this, Laya is no more sure than the LLM it would overrule.
CONFIDENT = 0.55
# Below this even as a last resort the pick is noise, and "other" is the honest label.
_FLOOR = 0.35

_SECTOR_CRITERIA = {
    "technology": "software, semiconductors, internet platforms, cyber security",
    "healthcare": "drugmakers, hospitals, medical devices, disease outbreaks",
    "financials": "banks, insurers, rates, currencies, sovereign debt, sanctions on finance",
    "energy": "oil, gas, refining, pipelines, shipping lanes for crude and LNG",
    "consumer": "retail, food, autos, travel and household spending",
    "industrials": "defense contractors, aerospace, shipping, freight, manufacturing, tariffs",
    "materials": "metals, mining, grains, fertilizer, chemicals",
    "utilities": "power grids, electricity and water providers",
    "real_estate": "property, housing, REITs, construction demand",
    "communications": "telecom, media, satellites, undersea cables",
}
# "other" is left out on purpose: the checkpoint ships no valid calibration for
# 11+ options, and ten keep confidence meaningful. Low confidence stands in for it.
assert set(_SECTOR_CRITERIA) == set(TAXONOMY) - {"other"}

_QUESTIONS = {
    "sector": {
        "type": "choice",
        "instructions": "Which market sector's revenues or costs does this news move most?",
        "criteria": _SECTOR_CRITERIA,
    },
    "direction": {
        "type": "choice",
        "instructions": "Which way does this news push the prices of the assets it affects?",
        "criteria": {
            "positive": "prices of affected companies or commodities likely rise",
            "negative": "prices of affected companies or commodities likely fall",
            "neutral": "no clear price effect, or effects cancel out",
        },
    },
}


@dataclass(frozen=True)
class LayaView:
    sector: str
    sector_p: float
    direction: str
    direction_p: float


_lock = threading.Lock()
_predict: Any = None
_unavailable = False
_stamp: float | None = None  # mtime of the loaded _MODEL weights


def _weights_mtime() -> float | None:
    try:
        return os.stat(os.path.join(_MODEL, "model.safetensors")).st_mtime
    except OSError:  # absent mid-promotion (daily.py swaps the directory)
        return None


def _load() -> Any:
    """Return a `predict(state, questions)` callable, or None when no runtime loads.

    A promoted checkpoint replaces the weights under _MODEL; the next call picks it up.
    """
    global _predict, _unavailable, _stamp
    if _stamp is not None and _weights_mtime() not in (None, _stamp):
        logger.info("Laya checkpoint changed, reloading")
        _predict, _stamp = None, None
    if _predict is not None or _unavailable:
        return _predict
    if os.environ.get("FINSCRAPE_LAYA", "").lower() in ("0", "false", "no", "off"):
        _unavailable = True
        return None
    try:
        if sys.platform == "darwin" and platform.machine() == "arm64":
            import laya_mlx

            _predict = laya_mlx.load(_MLX_REPO, dtype="float16").predict
        elif _MODEL:
            from laya import Agent

            _stamp = _weights_mtime()
            _predict = Agent(_MODEL).predict
        else:
            from laya import Router

            _predict = Router().predict
        logger.info("Laya classifier loaded")
    except Exception as exc:  # missing package, weights download, torch init
        _unavailable = True
        logger.info("Laya unavailable, using LLM/keyword labels: %s", exc)
    return _predict


def _pick(answer: Any) -> tuple[str, float]:
    """(label, probability) from one choice answer.

    The two runtimes agree on `choice` but name the distribution differently,
    so read whichever mapping is present rather than pinning one version.
    """
    if not isinstance(answer, dict):
        return "", 0.0
    probs = next(
        (answer[k] for k in ("probabilities", "probs", "scores") if isinstance(answer.get(k), dict)),
        {},
    )
    label = answer.get("choice")
    if not isinstance(label, str):
        label = max(probs, key=lambda k: probs[k]) if probs else ""
    try:
        p = float(probs.get(label, answer.get("probability", 0.0)))
    except (TypeError, ValueError):
        p = 0.0
    return label, p


def classify(title: str, text: str) -> LayaView | None:
    """Sector and direction for one article, or None when Laya is not installed."""
    state = f"{title}. {text}"[:_MAX_CHARS] if title else text[:_MAX_CHARS]
    # One lock for load and predict: worker threads would otherwise race to load
    # the ~800MB checkpoint twice.
    with _lock:
        predict = _load()
        if predict is None:
            return None
        try:
            result = predict(state, _QUESTIONS)
        except Exception as exc:
            logger.warning("Laya predict failed: %s", exc)
            return None
    answers = (result or {}).get("answers") or {}
    sector, sector_p = _pick(answers.get("sector"))
    direction, direction_p = _pick(answers.get("direction"))
    return LayaView(sector, sector_p, direction, direction_p)


def choose_sector(
    llm_sector: str,
    view: LayaView | None,
    keyword_sector: str,
    tickers: Iterable[str] = (),
) -> str:
    """Confident Laya label, then the LLM's, then keywords, then the sector of the
    companies named, then a plausible Laya pick, else "other".

    The LLM's "technology" counts only with keyword or company support: it is the
    label the LLM stamps on purely political stories, the defect this chain exists to fix.
    """
    laya_p = view.sector_p if view and view.sector in TAXONOMY else 0.0
    if laya_p >= CONFIDENT:
        return view.sector  # type: ignore[union-attr]
    company = Counter(TICKER_SECTOR[t] for t in tickers if t in TICKER_SECTOR)
    llm = next((s for s in normalize(llm_sector) if s in TAXONOMY and s != "other"), "")
    if llm == "technology" and keyword_sector != "technology" and "technology" not in company:
        llm = ""
    top = company.most_common(2)
    # A tie (Walmart vs Uber) says nothing about which sector the story is about.
    company_sector = top[0][0] if top and (len(top) == 1 or top[0][1] > top[1][1]) else ""
    fallback = view.sector if view and laya_p >= _FLOOR else "other"
    return llm or keyword_sector or company_sector or fallback


def disagrees(llm_direction: str, view: LayaView | None) -> bool:
    """True when Laya confidently calls the opposite price direction to the LLM."""
    if not view or view.direction_p < CONFIDENT:
        return False
    return {llm_direction, view.direction} == {"positive", "negative"}
