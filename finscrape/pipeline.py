"""
FinScrape Pipeline — turns one scraped article into a scored event.

Flow: AI analysis → NLP + ticker fusion → validation → score → dedup against the
caller's EventStore. The worker supplies the articles and owns storage.
"""

from __future__ import annotations

import logging
import re
import threading
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any, Protocol

from finscrape.agents import DEFAULT_AGENTS, AgentCouncil
from finscrape.analysis import laya, sp500
from finscrape.analysis.ai_client import begin_analysis, budget_blocked, call_ai
from finscrape.analysis.embeddings import most_similar
from finscrape.analysis.fallback import analyze_without_llm
from finscrape.analysis.market_reaction import apply_market_confirmation
from finscrape.analysis.nlp import FinancialNLP
from finscrape.analysis.prompts import render_prompt
from finscrape.analysis.validator import (
    calculate_heuristic_score,
    calibrate_signal_score,
    check_divergence,
    clean_tickers,
    fuse_confidence,
    grounded_tickers,
    is_market_relevant,
)
from finscrape.extract.entity_map import lede_tickers, resolve_company_tickers
from finscrape.market_data import get_indicators, get_market_reaction
from finscrape.models import FinEvent, ScrapedArticle, Verdict
from finscrape.settings import env, env_bool

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
        """`use_council` is an offline/experimental mode only (plan M1.7).

        Production runs one `call_ai` per article plus deterministic layers (Laya
        sector/direction, spaCy, the entity/lede maps, market facts). The council
        issues eight calls per article and scores a weighted vote, which is not the
        product the dashboard advertises — so asking for it in production is refused
        rather than silently tripling the bill.
        """
        self.event_store = event_store
        # Per-thread: the worker analyzes several sources concurrently on one pipeline.
        self._tls = threading.local()
        self.nlp = FinancialNLP()
        self.use_council = use_council
        if use_council and (env("WORLDFIN_ENV", "") or "").lower() == "production":
            raise RuntimeError(
                "the agent council is an offline/experimental mode: production is one "
                "LLM call per article (plan M1.7)"
            )
        self.council = AgentCouncil(agents=DEFAULT_AGENTS, judge=True) if use_council else None

    def _analyze_article(self, source_name: str, article: ScrapedArticle) -> FinEvent | None:
        """Run AI analysis + heuristic validation on a single article."""
        self._tls.merged_into = None
        self._tls.ai_failed = False
        begin_analysis()

        # Pre-LLM relevance gate: junk lifestyle pieces and transient event
        # briefs (minor quakes, forming storms) never reach the AI or the DB.
        if not is_market_relevant(article.title, article.text):
            logger.debug(
                "stage=relevance skip: off-topic or transient brief (source=%s title=%r)",
                source_name,
                article.title[:70],
            )
            return None

        # NLP runs for every judged article; the fallback reuses this result so an
        # LLM outage does not pay for a second spaCy pass.
        nlp_result = self.nlp.analyze(article.title, article.text)

        # Choose analysis mode: multi-agent council or single AI call
        if self.council:
            result = self._analyze_with_council(source_name, article)[0]
        else:
            result = self._analyze_with_single_ai(article)

        if not result:
            # Zero-cost mode: LLM unavailable / budget-capped -> heuristic + entity-map
            # tickers so ingestion never stalls (opt-in: FINSCRAPE_HEURISTIC_FALLBACK).
            # A budget block forces the downgrade even when the opt-in is off, and the
            # row records the reason so it can be re-analysed later.
            budget_downgrade = budget_blocked()
            if env_bool("FINSCRAPE_HEURISTIC_FALLBACK") or budget_downgrade:
                result = self._heuristic_only(article, nlp_result)
                if result is not None and budget_downgrade:
                    result.setdefault("key_metrics", {})[
                        "fallback_reason"
                    ] = "daily_token_ceiling"
                    logger.warning(
                        "stage=analysis budget downgrade: daily token ceiling reached "
                        "(source=%s title=%r)",
                        source_name,
                        article.title[:70],
                    )
            if not result:
                self._tls.ai_failed = True
                logger.warning(
                    "stage=analysis failed: no model and no heuristic fallback "
                    "(source=%s title=%r)",
                    source_name,
                    article.title[:70],
                )
                return None

        if not result.get("relevant", False):
            logger.debug(
                "stage=analysis skip: model marked it not relevant (source=%s title=%r)",
                source_name,
                article.title[:70],
            )
            return None

        full_text = article.title + " " + article.text

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
            logger.debug(
                "stage=tickers skip: no grounded symbol (source=%s title=%r)",
                source_name,
                article.title[:70],
            )
            return None

        laya_view = laya.classify(article.title, article.text)
        market_reaction = get_market_reaction(valid_tickers[:8])

        # Heuristic validation
        h_sentiment, h_impact = calculate_heuristic_score(full_text, result.get("event_type", ""))
        # The fallback already translates the event into a market direction; a
        # sentiment mismatch ("prices rose" in a conflict story) must not clamp it.
        heuristic = result.get("key_metrics", {}).get("analysis_source") == "heuristic"
        divergence = False if heuristic else check_divergence(
            result.get("impact_direction", "neutral"), h_sentiment
        )

        # Final scoring: the LLM's number is rescaled to the magnitude/actionability
        # it chose, so routine stories stop clustering on ±3.
        final_score = calibrate_signal_score(
            result.get("signal_score", 0),
            result.get("magnitude", "medium"),
            result.get("actionability", "medium"),
            result.get("novelty", "standard"),
        )
        # Text and model disagree on polarity, so neither direction is trustworthy.
        if divergence:
            final_score = max(-2, min(2, final_score))

        # The tape is evidence, not a new opinion: an aligned spike can lift the
        # call, an opposing spike lowers confidence, but neither changes the sign.
        confirmation = apply_market_confirmation(
            final_score, result.get("impact_direction", "neutral"), market_reaction
        )
        if not divergence and confirmation.delta:
            final_score += (1 if final_score > 0 else -1) * confirmation.delta
            final_score = max(-5, min(5, final_score))
        confidence = fuse_confidence(
            result.get("confidence", 0.5),
            source_name,
            article.age_hours,
            divergence,
            nlp_result.has_breaking_indicators,
        )
        confidence = max(0.0, min(1.0, confidence + confirmation.confidence))
        if not divergence:
            if confirmation.magnitude:
                result["magnitude"] = confirmation.magnitude
            if confirmation.actionability:
                result["actionability"] = confirmation.actionability

        # Only companies the text names: region keywords map to proxies like TSM
        # for "Taiwan", which would pass a political story off as technology.
        sector = laya.choose_sector(
            result.get("sector_impact", ""), laya_view, nlp_result.sector,
            tickers=company_tickers + sp500.headline_tickers(article.title),
        )

        # Merge NLP-extracted metrics into key_metrics
        nlp_metrics = {}
        for m in nlp_result.metrics:
            nlp_metrics[m.metric_type] = {"value": m.value, "raw": m.context}
        key_metrics = result.get("key_metrics", {})
        if market_reaction:
            top = sorted(
                market_reaction.values(),
                key=lambda row: abs(float(row.get("change_percent", 0)))
                * min(float(row.get("volume_ratio", 1.0) or 1.0), 5.0),
                reverse=True,
            )[:3]
            key_metrics["market_reaction"] = top
        # Which layer picked the sector, kept on the row so the UI can show the chain
        # rather than only the winner (plan m4.2.1, m5.1).
        key_metrics["sector_chain"] = {
            "laya": getattr(laya_view, "sector", "") or "",
            "model": str(result.get("sector_impact") or ""),
            "keyword": str(getattr(nlp_result, "sector", "") or ""),
            "chosen": sector,
        }
        if confirmation.evidence:
            key_metrics["market_confirmation"] = confirmation.evidence
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
            # Which judge wrote this row, so a heuristic and a judged row never look alike
            # (plan m1.3.1). `_validate_response` and the fallback both stamp it; a council
            # verdict is model output by construction.
            analysis_source=result.get("analysis_source") or ("heuristic" if heuristic else "model"),
            model_name=result.get("model_name", ""),
            excerpt=" ".join(article.text.split())[:600],
            source_seen={source_name: datetime.now(UTC).isoformat()},
        )

        # Deduplication
        matched = self._find_duplicate(event)
        if matched:
            logger.info(
                "stage=dedup merge: into #%s %r (source=%s)",
                matched.get("id"),
                str(matched.get("subject", ""))[:60],
                source_name,
            )
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
            logger.info(
                "stage=score %-8s %s (source=%s score=%s)",
                event.verdict,
                event.subject,
                source_name,
                event.signal_score,
            )
            if event.reasoning:
                logger.debug("stage=score reasoning: %s", event.reasoning[:120])
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

    def _heuristic_only(
        self, article: ScrapedArticle, nlp_result=None
    ) -> dict | None:
        """LLM-free analysis: a deterministic event call, not sentiment alone.

        Returns None when no market event is recognisable or no listed expression
        resolves, so an outage never publishes a 0 OBSERVE for unrelated politics.
        Tagged `prompt_variant='heuristic'` so it is distinguishable and enrichable.
        """
        if nlp_result is None:
            nlp_result = self.nlp.analyze(article.title, article.text)
        return analyze_without_llm(
            article.title,
            article.text,
            nlp_result,
            raw_tickers=list(article.raw_tickers or []),
        )

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
        council = self.council
        if council is None:
            return None, None
        metadata = {"source": source_name, "age_hours": f"{article.age_hours:.1f}"}
        full_text = article.title + " " + article.text
        tickers = sorted(set(lede_tickers(article.title, article.text) + resolve_company_tickers(full_text)))
        market_facts = get_indicators(tickers) if tickers else {}

        cv = council.deliberate(article.title, article.text, metadata, market_facts)

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
