"""
FinScrape Pipeline — turns one scraped article into a scored event.

Flow: AI analysis → NLP + ticker fusion → validation → score → dedup against the
caller's EventStore. The worker supplies the articles and owns storage.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from difflib import SequenceMatcher
from typing import Any, Protocol

from finscrape.agents import DEFAULT_AGENTS, AgentCouncil
from finscrape.analysis import laya
from finscrape.analysis.ai_client import call_ai
from finscrape.analysis.nlp import FinancialNLP
from finscrape.analysis.prompts import render_prompt
from finscrape.analysis.validator import (
    calculate_heuristic_score,
    check_divergence,
    clean_tickers,
    grounded_tickers,
    fuse_confidence,
    is_market_relevant,
)
from finscrape.analysis.embeddings import most_similar
from finscrape.entity_map import lede_tickers, resolve_company_tickers
from finscrape.market_data import (
    calculate_market_boost,
    get_indicators,
    get_market_data,
)
from finscrape.models import FinEvent, ScrapedArticle, Verdict

logger = logging.getLogger(__name__)


class EventStore(Protocol):
    """Where dedup reads recent events and records new ones."""

    @property
    def events(self) -> list[dict]: ...

    def add_event(self, event: dict) -> int: ...

    def update_event(self, event_id: int, **kwargs: Any) -> None: ...


class FinScrapePipeline:
    """Analyze one article at a time into a FinEvent, deduped against `event_store`."""

    def __init__(self, event_store: EventStore, use_council: bool = False):
        self.event_store = event_store
        # Per-thread: the worker analyzes several sources concurrently on one pipeline.
        self._tls = threading.local()
        self.nlp = FinancialNLP()
        self.use_council = use_council
        self.council = AgentCouncil(agents=DEFAULT_AGENTS, judge=True) if use_council else None

    def _analyze_article(self, source_name: str, article: ScrapedArticle) -> FinEvent | None:
        """Run AI analysis + heuristic validation on a single article."""
        self._tls.merged_into = None
        self._tls.ai_failed = False

        # Pre-LLM relevance gate: junk lifestyle pieces and transient event
        # briefs (minor quakes, forming storms) never reach the AI or the DB.
        if not is_market_relevant(article.title, article.text):
            print("    [SKIP] Not market-relevant (off-topic or transient brief)")
            return None

        # Choose analysis mode: multi-agent council or single AI call
        if self.council:
            result, council_verdict = self._analyze_with_council(source_name, article)
        else:
            result, council_verdict = self._analyze_with_single_ai(article), None

        if not result:
            # Zero-cost mode: LLM unavailable / budget-capped → heuristic + entity-map
            # tickers so ingestion never stalls (opt-in: FINSCRAPE_HEURISTIC_FALLBACK).
            # The event lands with a heuristic verdict, enrichable on demand (/api/ai/analyze).
            if os.getenv("FINSCRAPE_HEURISTIC_FALLBACK", "").lower() in ("1", "true", "yes"):
                result = self._heuristic_only(article)
            if not result:
                self._tls.ai_failed = True
                print("    [ERROR] AI analysis failed")
                return None

        if not result.get("relevant", False):
            print("    [SKIP] Not market-relevant")
            return None

        # NLP analysis — entity extraction, metrics, sector, breaking news
        full_text = article.title + " " + article.text
        nlp_result = self.nlp.analyze(article.title, article.text)

        # Ticker processing — combine AI, NLP, entity index, regex, and sector-map
        ai_tickers = result.get("tickers", [])
        nlp_tickers = nlp_result.tickers
        regex_tickers = article.raw_tickers
        # Sector/geopolitics keyword → tickers (Phase 12): rescues world headlines that
        # name a sector/region but no company, where the LLM left tickers blank.
        # Company-name resolution (SEC list) catches articles naming the company outright.
        sector_tickers = lede_tickers(article.title, article.text)
        company_tickers = resolve_company_tickers(full_text)

        # Also extract tickers from affected_entities
        entity_obj_tickers = [
            e.get("ticker", "")
            for e in result.get("affected_entities", [])
            if e.get("ticker")
        ]

        text_tickers = (
            nlp_tickers + regex_tickers + sector_tickers + company_tickers
        )
        all_symbols = set(
            text_tickers
            + grounded_tickers(
                ai_tickers + entity_obj_tickers,
                result.get("affected_entities", []),
                text_tickers,
                full_text,
            )
        )
        valid_tickers = clean_tickers([
            t for t in all_symbols
            if isinstance(t, str) and 1 < len(t) <= 5 and t.isupper()
        ], text=full_text)

        if not valid_tickers:
            print("    [SKIP] No valid tickers found")
            return None

        laya_view = laya.classify(article.title, article.text)

        # Market data
        market_data = get_market_data(valid_tickers)
        market_boost = calculate_market_boost(market_data)

        # Heuristic validation
        h_sentiment, h_impact = calculate_heuristic_score(full_text, result.get("event_type", ""))
        divergence = check_divergence(
            result.get("impact_direction", "neutral"), h_sentiment
        ) or laya.disagrees(result.get("impact_direction", "neutral"), laya_view)

        # Final scoring
        base_score = result.get("signal_score", 0)
        final_score = max(-5, min(5, base_score + market_boost))
        confidence = fuse_confidence(
            result.get("confidence", 0.5),
            source_name,
            article.age_hours,
            divergence,
            nlp_result.has_breaking_indicators,
        )

        # Only companies the text names: region keywords map to proxies like TSM
        # for "Taiwan", which would pass a political story off as technology.
        sector = laya.choose_sector(
            result.get("sector_impact", ""), laya_view, nlp_result.sector,
            tickers=company_tickers,
        )

        # Merge NLP-extracted metrics into key_metrics
        nlp_metrics = {}
        for m in nlp_result.metrics:
            nlp_metrics[m.metric_type] = {"value": m.value, "raw": m.context}
        key_metrics = result.get("key_metrics", {})
        for k, v in nlp_metrics.items():
            if k not in key_metrics:
                key_metrics[k] = v

        # Build event with enriched fields
        subject = " ".join(str(result.get("subject") or article.title).split())
        verdict = Verdict.from_score(final_score)

        event = FinEvent(
            subject=subject,
            event_type=result.get("event_type", "other"),
            tickers=valid_tickers,
            impact_direction=result.get("impact_direction", "neutral"),
            signal_score=final_score,
            confidence=round(confidence, 2),
            verdict=verdict.value,
            heuristic_impact=h_impact,
            divergence_flag=divergence,
            sources=[source_name],
            articles=[article.url],
            # New enriched fields from chain-of-thought analysis
            reasoning=result.get("reasoning", ""),
            magnitude=result.get("magnitude", "medium"),
            novelty=result.get("novelty", "standard"),
            actionability=result.get("actionability", "medium"),
            affected_entities=result.get("affected_entities", []),
            second_order_effects=result.get("second_order_effects", []),
            sector_impact=sector,
            key_metrics=key_metrics,
        )

        # Deduplication
        matched = self._find_duplicate(event)
        if matched:
            print(f"    [MERGE] Merging with: {matched.get('subject', '')[:50]}")
            articles_list = matched.get("articles", [])
            sources_list = matched.get("sources", [])
            updated = {}
            if article.url not in articles_list:
                articles_list.append(article.url)
                updated["articles"] = articles_list
            if source_name not in sources_list:
                sources_list.append(source_name)
                updated["sources"] = sources_list
            if updated and matched.get("id"):
                self.event_store.update_event(matched["id"], **updated)
            self._tls.merged_into = matched
            return None
        else:
            print(f"    [{event.verdict:8s}] {event.subject}")
            if event.reasoning:
                print(f"           Reasoning: {event.reasoning[:80]}...")
            self.event_store.add_event(event.to_dict())
            return event

    def merged_into(self) -> dict | None:
        """The stored event this thread's last `_analyze_article` merged into, if any.

        Merges only update `event_store` rows that carry an id; a caller whose store
        defers writes (the worker's Postgres) reads this to apply the merge itself.
        """
        return getattr(self._tls, "merged_into", None)

    def ai_failed(self) -> bool:
        """True when this thread's last `_analyze_article` got no answer from the LLM,
        so the article was never judged and is worth retrying."""
        return getattr(self._tls, "ai_failed", False)

    def _heuristic_only(self, article: ScrapedArticle) -> dict | None:
        """LLM-free analysis (zero-cost mode): heuristic verdict + entity-map/regex tickers,
        shaped like a call_ai result. Returns None when no tickers resolve (can't place it).
        Tagged key_metrics.prompt_variant='heuristic' so it's distinguishable + enrichable."""
        full_text = article.title + " " + article.text
        symbols = sorted(
            set(lede_tickers(article.title, article.text) + resolve_company_tickers(full_text) + list(article.raw_tickers or []))
        )
        tickers = [t for t in symbols if isinstance(t, str) and 1 < len(t) <= 5 and t.isupper()]
        if not tickers:
            return None
        sentiment, impact = calculate_heuristic_score(full_text, "")
        mag = round(impact * 5)
        score = mag if sentiment == "positive" else -mag if sentiment == "negative" else 0
        return {
            "relevant": True,
            "event_type": "other",
            "subject": article.title[:120],
            "impact_direction": sentiment if sentiment in ("positive", "negative") else "neutral",
            "tickers": tickers,
            "affected_entities": [],
            "signal_score": int(max(-5, min(5, score))),
            "confidence": 0.4,
            "magnitude": "high" if impact >= 0.66 else "low" if impact < 0.33 else "medium",
            "novelty": "standard",
            "actionability": "low",
            "reasoning": "Heuristic analysis (LLM unavailable) — click to enrich with AI.",
            "key_metrics": {"prompt_variant": "heuristic"},
            "sector_impact": "",
            "second_order_effects": [],
        }

    def _analyze_with_single_ai(self, article: ScrapedArticle) -> dict | None:
        """Standard single-AI analysis. Picks a prompt variant (A/B, opt-in) and stamps
        it into key_metrics so accuracy can be compared per variant."""
        from finscrape.analysis.prompt_registry import get_prompts, pick_variant

        variant = pick_variant(article.title)
        system_prompt, analysis_prompt = get_prompts(variant)
        prompt = render_prompt(analysis_prompt, article.title, article.text)
        result = call_ai(prompt, system_prompt)
        if result is not None:
            result.setdefault("key_metrics", {})["prompt_variant"] = variant
        return result

    def _analyze_with_council(self, source_name: str, article: ScrapedArticle) -> tuple[dict | None, dict | None]:
        """Multi-agent council analysis. Returns (result_dict, council_verdict_dict).

        Tickers resolve before deliberation (same lede_tickers used by
        _heuristic_only) so real computed indicators can go into the council as
        GROUND TRUTH facts — the council itself fetches nothing, stays pure.
        """
        metadata = {"source": source_name, "age_hours": f"{article.age_hours:.1f}"}
        full_text = article.title + " " + article.text
        tickers = sorted(set(lede_tickers(article.title, article.text) + resolve_company_tickers(full_text)))
        market_facts = get_indicators(tickers) if tickers else {}

        cv = self.council.deliberate(article.title, article.text, metadata, market_facts)

        # If no individual verdicts produced anything useful, fail
        if cv.consensus_confidence < 0.05:
            return None, None

        # Convert council verdict into the standard result dict format
        # so downstream ticker/NLP/validation code works unchanged
        reasoning = f"Council verdict ({cv.agreement_level:.0%} agreement): " + "; ".join(
            f"{v.agent_name}={v.signal_score}" for v in cv.individual_verdicts
        )
        if cv.judged:
            reasoning += f" | Judge override (raw mean {cv.consensus_score_raw}): {cv.judge_rationale}"

        result = {
            "relevant": True,
            "event_type": "other",
            "tickers": [],
            "impact_direction": "positive" if cv.consensus_score > 0 else ("negative" if cv.consensus_score < 0 else "neutral"),
            "signal_score": round(cv.consensus_score),
            "confidence": cv.consensus_confidence,
            "subject": article.title,
            "reasoning": reasoning,
            "magnitude": "medium",
            "novelty": "standard",
            "actionability": "medium",
            "affected_entities": [],
            "second_order_effects": [],
            "sector_impact": "",
            "key_metrics": {},
        }

        # Merge tickers from all agents
        all_tickers = []
        for v in cv.individual_verdicts:
            all_tickers.extend(v.tickers)
        result["tickers"] = list(set(all_tickers))

        # Add council-specific metadata
        council_dict = cv.to_dict()
        council_dict.pop("individual_verdicts", None)  # too large for storage
        result["council"] = council_dict
        result["key_risks"] = cv.key_risks[:5]
        result["key_opportunities"] = cv.key_opportunities[:5]

        return result, council_dict

    def _normalize_subject(self, s: str) -> str:
        s = s.lower()
        s = re.sub(r"[^\w\s]", "", s)
        s = re.sub(r"\s+", " ", s)
        return s.strip()

    def _find_duplicate(self, new_event: FinEvent) -> dict | None:
        """Check if this event already exists in recent history.

        Gate 1: ticker overlap + same event type. Gate 2: subject similarity —
        first by character ratio, then (Phase 13) by embedding cosine, which
        catches paraphrased coverage of the same story across sources.
        """
        recent = self.event_store.events[-100:]
        candidates: list[tuple[int, str]] = []
        for idx, e in enumerate(recent):
            existing_tickers = e.get("tickers", [])
            if not existing_tickers or not new_event.tickers:
                continue

            overlap = len(set(new_event.tickers) & set(existing_tickers))
            ratio = overlap / min(len(set(new_event.tickers)), len(set(existing_tickers)))

            if ratio >= 0.5 and e.get("event_type") == new_event.event_type:
                candidates.append((idx, e.get("subject", "")))

        for idx, existing_subject in candidates:
            if SequenceMatcher(
                None,
                self._normalize_subject(existing_subject),
                self._normalize_subject(new_event.subject),
            ).ratio() >= 0.85:
                return recent[idx]

        # Embedding fallback: paraphrased duplicates the character ratio misses.
        # 0.62 is calibrated for nomic-embed-text (same-story paraphrases ~0.70,
        # unrelated ~0.44); the structural gate above keeps false merges away.
        # No-ops (returns None) whenever Ollama is unavailable.
        if candidates:
            match = most_similar(
                new_event.subject,
                [(subject, subject) for _, subject in candidates],
                threshold=0.62,
            )
            if match:
                matched_subject, _score = match
                for idx, subject in candidates:
                    if subject == matched_subject:
                        return recent[idx]

        return None
