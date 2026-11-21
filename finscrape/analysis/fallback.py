"""Deterministic analyst used when every LLM attempt fails.

The LLM is the preferred judge, but an outage must not turn the feed into
sentiment-only noise. This module turns the NLP layer into a structured call:
it recognises the event, its direction and size, whether a trader could act,
and which listed expressions are exposed. It is intentionally rule-based and
offline: no network, no model, same answer every run.

The output uses the same shape as `call_ai`, so `_analyze_article` can pass it
through calibration, confidence fusion and ticker validation unchanged.

Design rules:
  - Event polarity comes from the event, not the article's mood. "Stocks fall
    after a ceasefire" is still a de-escalation story.
  - Magnitude comes from figures and scale words, not adjectives alone.
  - A story with no recognisable market event is `None`, not a 0 OBSERVE.
  - A company named in the text outranks a region/sector proxy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from finscrape.analysis.nlp import NLPResult
from finscrape.analysis.sp500 import sector as sp500_sector
from finscrape.analysis.ticker_map import TICKER_SECTOR
from finscrape.analysis.validator import (
    calculate_sentence_sentiment,
    extract_financial_magnitudes,
)
from finscrape.entity_map import (
    lede_tickers,
    listed_titles,
    resolve_company_tickers,
    resolve_tickers,
)

_MAX_TICKERS = 8
# Liquid expressions for events that name no company and no mapped region. Used
# only when the text itself yields no direct ticker and no lede proxy.
_RULE_PROXIES: dict[str, tuple[str, ...]] = {
    "conflict_escalation": ("ITA", "GLD", "XLE"),
    "ceasefire": ("ITA", "SPY"),
    "sanctions": ("GLD", "XLE"),
    "tariffs": ("FXI", "SPY"),
    "trade_deal": ("FXI", "SPY"),
    "supply_disruption": ("XLE", "USO"),
    "rate_hike": ("TLT", "SPY"),
    "rate_cut": ("TLT", "SPY"),
    "inflation_hot": ("TLT", "SPY"),
    "inflation_cool": ("TLT", "SPY"),
    "bankruptcy": ("HYG", "XLF"),
    "cyber_attack": ("HACK", "CRWD"),
    "disaster": ("KIE", "XLB"),
}
_UNCERTAIN = re.compile(
    r"\b(reportedly|sources? say|may|might|could|considering|in talks|plans? to|"
    r"weighs?|expected to|rumou?r)\b",
    re.IGNORECASE,
)
_REHASH = re.compile(
    r"\b(reiterat\w*|unchanged|again|continues?|weeks? after|months? after|"
    r"remains?|still)\b",
    re.IGNORECASE,
)
_FOLLOW_UP = re.compile(
    r"\b(after|following|update|latest|extends?|second round)\b", re.IGNORECASE
)
_BREAKING = re.compile(
    r"\b(breaking|just in|announces?|launches?|declares?|imposes?|strikes?|attacks?)\b",
    re.IGNORECASE,
)
_SCALE_UP = re.compile(
    r"\b(all|nationwide|global|total|complete|record|largest|unprecedented|"
    r"emergency|entire|widespread|systemic)\b",
    re.IGNORECASE,
)
_SCALE_DOWN = re.compile(
    r"\b(minor|limited|partial|small|some|slight|isolated)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class EventRule:
    """One recognisable market event and the call it implies."""

    key: str
    event_type: str
    direction: int  # +1 positive, -1 negative, 0 no directional call
    severity: int  # 1..5 before magnitude adjustment
    actionability: str  # low / medium / high
    sector: str
    patterns: tuple[str, ...] | str
    effects: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # A single parenthesised pattern literal is a str, not a tuple; normalise
        # so callers can write one readable regex without a trailing comma trap.
        if isinstance(self.patterns, str):
            object.__setattr__(self, "patterns", (self.patterns,))

    @property
    def regex(self) -> re.Pattern[str]:
        return _compiled(self)


_RULES: tuple[EventRule, ...] = (
    EventRule(
        "conflict_escalation",
        "geopolitical_event",
        -1,
        4,
        "high",
        "industrials",
        (
            r"\b(airstrikes?|air[- ]strikes?|missile (?:strikes?|attacks?)|drone (?:strikes?|attacks?)|"
            r"shelling|bombardment|invasion|invades|ground offensive|military offensive|"
            r"troops (?:mass|advance|enter)|mobiliz(?:e|ation)|declares? war|"
            r"war(?:planes|ships)|blockade|shoots? down|assassinat(?:e|ed|ion)|"
            r"military escalation|escalat(?:e|es|ing) (?:military|tensions|conflict)|"
            r"military threats?|armed (?:attack|conflict))\b"
        ),
        ("Defense demand rises; energy, freight and insurance risk premia widen.",),
    ),
    EventRule(
        "ceasefire",
        "geopolitical_event",
        1,
        4,
        "high",
        "industrials",
        (
            r"\b(ceasefire|truce|peace (?:deal|agreement|talks)|de[- ]escalat\w*|"
            r"withdraw(?:s|al|ing)? (?:troops|forces)|hostage release|prisoner exchange|"
            r"ends? (?:the )?(?:war|conflict)|settlement)\b"
        ),
        ("Risk premia fall; reconstruction, shipping and travel names may benefit.",),
    ),
    EventRule(
        "sanctions",
        "regulatory_decision",
        -1,
        3,
        "medium",
        "financials",
        (
            r"\b(sanctions?|sanctioned|embargo|export controls?|asset freeze|blacklist|"
            r"secondary sanctions|financial restrictions)\b"
        ),
        ("Compliance costs rise and trade flows reroute.",),
    ),
    EventRule(
        "tariffs",
        "regulatory_decision",
        -1,
        3,
        "high",
        "industrials",
        (
            r"\b(tariffs?|import duties|trade war|export ban|export restrictions?|quotas?|"
            r"customs duties|retaliat(?:e|ion|ory) (?:tariffs|duties))\b"
        ),
        ("Import costs and retaliatory duties pressure margins.",),
    ),
    EventRule(
        "trade_deal",
        "regulatory_decision",
        1,
        3,
        "high",
        "industrials",
        (
            r"\b(trade (?:deal|agreement|pact)|lifts? (?:tariffs|sanctions)|"
            r"removes? (?:tariffs|sanctions)|opens? (?:market|border)|"
            r"normaliz(?:e|es|ation) (?:trade|relations))\b"
        ),
        ("Tariff relief and reopened markets help exporters and shippers.",),
    ),
    EventRule(
        "supply_disruption",
        "geopolitical_event",
        -1,
        4,
        "high",
        "energy",
        (
            r"\b((?:oil|gas|lng|crude) (?:supply|exports?|shipments?) "
            r"(?:cut|halt|disrupt|suspend)|production cut|output cut|"
            r"pipeline (?:shutdown|fire|attack|leak)|refinery (?:fire|outage|shutdown)|"
            r"strait of hormuz|suez canal|shipping (?:lane|route)s? (?:closed|blocked|disrupted)|"
            r"tanker (?:attack|seized)|chokepoint)\b"
        ),
        ("Input costs rise for energy users; producers and tanker owners gain.",),
    ),
    EventRule(
        "rate_hike",
        "market_movement",
        -1,
        3,
        "high",
        "financials",
        (
            r"\b(rate (?:hike|increase)|raises? (?:interest )?rates|hawkish|"
            r"tighten(?:ing|s) (?:monetary )?policy|higher-for-longer)\b"
        ),
        ("Higher discount rates pressure long-duration equities; banks may benefit.",),
    ),
    EventRule(
        "rate_cut",
        "market_movement",
        1,
        3,
        "high",
        "financials",
        (
            r"\b(rate (?:cut|reduction)|cuts? (?:interest )?rates|dovish|"
            r"eases? (?:monetary )?policy|stimulus)\b"
        ),
        ("Lower discount rates support growth equities and rate-sensitive demand.",),
    ),
    EventRule(
        "inflation_hot",
        "market_movement",
        -1,
        3,
        "medium",
        "financials",
        (
            r"\b(inflation (?:rose|accelerat\w*|surge\w*|hot|higher)|"
            r"cpi (?:rose|jump\w*|accelerat\w*)|"
            r"prices? (?:rose|surged) (?:more than|sharply))\b"
        ),
        ("Sticky inflation keeps policy tight and pressures valuations.",),
    ),
    EventRule(
        "inflation_cool",
        "market_movement",
        1,
        2,
        "medium",
        "financials",
        (
            r"\b(inflation (?:fell|eased|cooled|slowed)|"
            r"cpi (?:fell|eased|slowed)|disinflation)\b"
        ),
        ("Cooling inflation supports easier policy and risk appetite.",),
    ),
    EventRule(
        "earnings_beat",
        "earnings",
        1,
        3,
        "high",
        "",
        (
            r"\b((?:beats?|topped|exceeded) (?:estimates|expectations|forecasts)|"
            r"earnings (?:rose|surged|jumped)|revenue (?:rose|grew|surged)|"
            r"record (?:profit|revenue)|raised (?:guidance|outlook|forecast))\b"
        ),
        ("Peer read-across and upward estimate revisions.",),
    ),
    EventRule(
        "earnings_miss",
        "earnings",
        -1,
        3,
        "high",
        "",
        (
            r"\b((?:missed|misses|below) (?:estimates|expectations|forecasts)|"
            r"earnings (?:fell|plunged|slumped)|revenue (?:fell|declined|dropped)|"
            r"profit warning|cut (?:guidance|outlook|forecast))\b"
        ),
        ("Peer read-across and downward estimate revisions.",),
    ),
    EventRule(
        "merger_acquisition",
        "merger_acquisition",
        1,
        3,
        "high",
        "",
        (
            r"\b(acqui(?:re|res|red|sition)|merger|takeover|buyout|"
            r"stake (?:sale|purchase)|tender offer|combine(?:s|d)? (?:with|business))\b"
        ),
        ("Deal completion risk and a re-rating of the target and peers.",),
    ),
    EventRule(
        "bankruptcy",
        "bankrupt",
        -1,
        5,
        "medium",
        "",
        (
            r"\b(bankrupt(?:cy)?|chapter 11|insolven(?:cy|t)|"
            r"default(?:s|ed)? on|debt restructuring|receivership|liquidation)\b"
        ),
        ("Creditors and suppliers face writedowns; competitors may gain share.",),
    ),
    EventRule(
        "regulatory_action",
        "regulatory_decision",
        -1,
        3,
        "medium",
        "",
        (
            r"\b(antitrust|regulator(?:s)? (?:probe|investigat\w*|fine|sue)|fined|"
            r"lawsuit|class action|recall|product ban|license (?:revoked|suspended)|probe into)\b"
        ),
        ("Legal and compliance costs rise; approvals may slip.",),
    ),
    EventRule(
        "regulatory_approval",
        "regulatory_decision",
        1,
        2,
        "medium",
        "",
        (
            r"\b(approved|approval|clears? (?:regulatory|antitrust)|"
            r"green[- ]lights?|wins? (?:approval|license))\b"
        ),
        ("Removes an overhang and brings the product or deal closer to revenue.",),
    ),
    EventRule(
        "cyber_attack",
        "geopolitical_event",
        -1,
        3,
        "medium",
        "technology",
        (
            r"\b(cyberattack|ransomware|data breach|hacked|security breach|"
            r"malware|phishing|ddos)\b"
        ),
        ("Remediation and insurance costs rise; security vendors see demand.",),
    ),
    EventRule(
        "disaster",
        "geopolitical_event",
        -1,
        3,
        "medium",
        "",
        (
            r"\b(earthquake|hurricane|typhoon|wildfire|flood|drought|"
            r"volcanic eruption|tsunami)\b"
        ),
        ("Damage estimates and reconstruction spending drive insurers and materials.",),
    ),
    EventRule(
        "investment",
        "investment_activity",
        1,
        2,
        "medium",
        "",
        (
            r"\b(invest(?:s|ment|ing)? (?:of )?\$?\d|capital expenditure|capex|"
            r"data cent(?:er|re)|new (?:factory|plant)|"
            r"expand(?:s|ing|ed)? (?:operations|production)|joint venture)\b"
        ),
        ("Capex and supplier orders follow the announcement.",),
    ),
    EventRule(
        "product_launch",
        "product_launch",
        1,
        2,
        "medium",
        "",
        (
            r"\b(launch(?:es|ed|ing)? (?:a |its )?(?:new )?product|unveil(?:s|ed)|"
            r"new (?:model|chip|drug|service)|wins? (?:contract|order))\b"
        ),
        ("Revenue timing depends on adoption and delivery.",),
    ),
    EventRule(
        "analyst_upgrade",
        "analyst_upgrade",
        1,
        2,
        "medium",
        "",
        (
            r"\b(upgrade(?:s|d)? (?:to|from)|raises? (?:price target|rating)|"
            r"initiates? (?:coverage )?(?:at )?(?:buy|overweight))\b"
        ),
        ("Flow and estimate revisions can follow a rating change.",),
    ),
    EventRule(
        "analyst_downgrade",
        "analyst_downgrade",
        -1,
        2,
        "medium",
        "",
        (
            r"\b(downgrade(?:s|d)?|cuts? (?:price target|rating)|"
            r"initiates? (?:coverage )?(?:at )?(?:sell|underweight))\b"
        ),
        ("Flow and estimate revisions can follow a rating change.",),
    ),
    EventRule(
        "ipo",
        "ipo",
        1,
        2,
        "medium",
        "",
        (r"\b(ipo|initial public offering|goes? public|listing)\b"),
        ("New supply may re-rate comparable listed peers.",),
    ),
    EventRule(
        "management_change",
        "management_change",
        0,
        2,
        "low",
        "",
        (
            r"\b(ceo (?:resign\w*|steps? down|departs|appointed)|"
            r"cfo (?:resign\w*|steps? down|departs)|management (?:shakeup|change)|"
            r"appoints? (?:a )?(?:new )?(?:ceo|cfo))\b"
        ),
        ("Strategy and execution risk are re-priced around the transition.",),
    ),
    EventRule(
        "market_move",
        "market_movement",
        0,
        2,
        "medium",
        "",
        (
            r"\b(stocks? (?:rose|fell|surged|plunged|rallied|slipped)|"
            r"shares? (?:rose|fell|surged|plunged)|selloff|rally|"
            r"market (?:gains|loses)|index (?:rose|fell))\b"
        ),
        (),
    ),
    EventRule(
        "defense_aid",
        "geopolitical_event",
        1,
        3,
        "medium",
        "industrials",
        (
            r"\b((?:military|defense|defence) (?:aid|assistance|package)|"
            r"arms? (?:deal|package|sale)|weapons? (?:package|sale|shipment)|"
            r"pledges? (?:air defense|military aid|weapons))\b"
        ),
        ("Defense contractors and suppliers see order visibility improve.",),
    ),
)

_COMPILED: dict[str, re.Pattern[str]] = {
    rule.key: re.compile("|".join(rule.patterns), re.IGNORECASE) for rule in _RULES
}


def _compiled(rule: EventRule) -> re.Pattern[str]:
    return _COMPILED[rule.key]


def _valid(symbol: str) -> bool:
    return isinstance(symbol, str) and 1 < len(symbol) <= 5 and symbol.isupper()


def _ordered_unique(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for symbol in symbols:
        if _valid(symbol) and symbol not in seen:
            seen.add(symbol)
            out.append(symbol)
    return out


def _direct_tickers(nlp: NLPResult, full_text: str, raw: list[str]) -> list[str]:
    """Companies the article names, strongest source first."""
    return _ordered_unique([*nlp.tickers, *resolve_company_tickers(full_text), *raw])


def _proxy_tickers(title: str, text: str, rule: EventRule) -> list[str]:
    """Sector/region proxies from the headline and lede, never the whole body."""
    proxies = lede_tickers(title, text)
    if not proxies:
        proxies = resolve_tickers(title)
    if not proxies:
        proxies = list(_RULE_PROXIES.get(rule.key, ()))
    return _ordered_unique(proxies)


def _pick_rule(full_text: str) -> tuple[EventRule | None, list[str]]:
    """Highest-evidence event rule, with the cue phrases that fired."""
    best: EventRule | None = None
    best_strength = 0.0
    best_cues: list[str] = []
    for rule in _RULES:
        cues = [m.group(0) for m in rule.regex.finditer(full_text)]
        if not cues:
            continue
        strength = rule.severity + min(len(cues), 4) * 0.35
        if strength > best_strength:
            best, best_strength, best_cues = rule, strength, cues
    return best, best_cues


def _magnitude_boost(figures: dict, full_text: str) -> int:
    boost = 0
    if any(
        figures.get(k) == "high"
        for k in ("dollar_magnitude", "percentage_magnitude", "layoff_magnitude")
    ):
        boost += 2
    elif any(
        figures.get(k) == "medium"
        for k in ("dollar_magnitude", "percentage_magnitude", "layoff_magnitude")
    ):
        boost += 1
    if _SCALE_UP.search(full_text):
        boost += 1
    if _SCALE_DOWN.search(full_text):
        boost -= 1
    casualties = re.search(
        r"\b(\d{1,6})\s+(?:killed|dead|casualties|injured)\b", full_text, re.IGNORECASE
    )
    if casualties:
        number = int(casualties.group(1))
        if number >= 100:
            boost += 2
        elif number >= 10:
            boost += 1
    return max(-1, min(3, boost))


def _novelty(full_text: str, nlp: NLPResult) -> str:
    if nlp.has_breaking_indicators or _BREAKING.search(full_text):
        return "breaking"
    if _REHASH.search(full_text):
        return "rehash"
    if _FOLLOW_UP.search(full_text):
        return "follow_up"
    return "standard"


def _confidence(
    cues: list[str],
    figures: dict,
    full_text: str,
    direct: list[str],
    novelty: str,
    mixed: bool,
) -> float:
    score = 0.42
    score += min(0.12, len(cues) * 0.03)
    if figures:
        score += 0.05
    if direct:
        score += 0.04
    if novelty == "breaking":
        score += 0.03
    if mixed:
        score -= 0.10
    if _UNCERTAIN.search(full_text):
        score -= 0.08
    return round(max(0.35, min(0.68, score)), 2)


def _actionability(base: str, direct: list[str], full_text: str) -> str:
    if _UNCERTAIN.search(full_text):
        return "low"
    if base == "high" and direct:
        return "high"
    if base == "high":
        return "medium"
    return base


def _sector(rule: EventRule, nlp: NLPResult, direct: list[str]) -> str:
    counts: dict[str, int] = {}
    for ticker in direct:
        sector = TICKER_SECTOR.get(ticker) or sp500_sector(ticker)
        if sector:
            counts[sector] = counts.get(sector, 0) + 1
    company_sector = max(counts, key=lambda name: counts[name]) if counts else ""
    return company_sector or nlp.sector or rule.sector


def _affected(direct: list[str], impact: str) -> list[dict[str, str]]:
    names = listed_titles()
    out: list[dict[str, str]] = []
    for index, ticker in enumerate(direct[:4]):
        name = names.get(ticker)
        if not name:
            continue
        out.append(
            {
                "name": name.title(),
                "ticker": ticker,
                "role": "primary" if index == 0 else "peer",
                "impact": impact
                if index == 0 and impact in ("positive", "negative")
                else "neutral",
            }
        )
    return out


def analyze_without_llm(
    title: str,
    text: str,
    nlp: NLPResult,
    raw_tickers: list[str] | None = None,
) -> dict | None:
    """Structured, deterministic analysis shaped like a `call_ai` result.

    Returns `None` when no market event is recognisable or no listed expression
    can be resolved, so the caller drops the article instead of publishing a
    sentiment-only call.
    """
    full_text = f"{title}. {text}".strip()
    rule, cues = _pick_rule(full_text)
    if rule is None:
        return None

    direct = _direct_tickers(nlp, full_text, list(raw_tickers or []))
    proxies = _proxy_tickers(title, text, rule)
    tickers = (direct or proxies)[:_MAX_TICKERS]
    if not tickers:
        return None

    figures = extract_financial_magnitudes(full_text)
    sentiment, sentiment_score = calculate_sentence_sentiment(full_text)
    direction = rule.direction
    mixed = False
    if direction == 0:
        if sentiment_score >= 1.5:
            direction = 1
        elif sentiment_score <= -1.5:
            direction = -1

    # Two credible events pulling opposite ways is a real "mixed", not a coin flip.
    opposite = [
        other
        for other in _RULES
        if other.direction == -rule.direction
        and other.direction != 0
        and other.regex.search(full_text)
        and other.severity + 0.35 >= rule.severity
    ]
    if opposite and direction != 0:
        mixed = True
        direction = 0

    severity = max(1, min(5, rule.severity + _magnitude_boost(figures, full_text)))
    score = 0 if direction == 0 else direction * severity
    magnitude = "high" if severity >= 4 else "medium" if severity >= 2 else "low"
    impact = (
        "mixed"
        if mixed
        else "positive"
        if direction > 0
        else "negative"
        if direction < 0
        else "neutral"
    )
    novelty = _novelty(full_text, nlp)
    actionability = _actionability(rule.actionability, direct, full_text)
    confidence = _confidence(cues, figures, full_text, direct, novelty, mixed)
    sector = _sector(rule, nlp, direct)

    key_metrics: dict = {
        "prompt_variant": "heuristic",
        "analysis_source": "heuristic",
        "fallback_event": rule.key,
        "fallback_cues": cues[:6],
        "sentiment": sentiment,
    }
    if figures:
        key_metrics["financial_figures"] = figures

    evidence = ", ".join(dict.fromkeys(cues[:4]))
    reasoning = (
        f"Deterministic fallback: {rule.key.replace('_', ' ')} matched {len(cues)} cue(s)"
        f" ({evidence}); tone {sentiment}; magnitude {magnitude}; "
        f"{len(direct)} named ticker(s), {len(proxies)} proxy ticker(s)."
    )

    return {
        "relevant": True,
        "event_type": rule.event_type,
        "subject": " ".join(title.split())[:120],
        "impact_direction": impact,
        "tickers": tickers,
        "affected_entities": _affected(direct, impact),
        "signal_score": int(max(-5, min(5, score))),
        "confidence": confidence,
        "magnitude": magnitude,
        "novelty": novelty,
        "actionability": actionability,
        "reasoning": reasoning,
        "key_metrics": key_metrics,
        "sector_impact": sector,
        "second_order_effects": list(rule.effects),
        # Same shape as `call_ai`: the row records which judge wrote it (plan m1.3.1).
        "analysis_source": "heuristic",
        "model_name": "",
    }
