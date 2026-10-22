"""One ingestion cycle per source: scrape → analyze → geocode → ingest → health.

Blocking finscrape work (scrape_news / ingestor.fetch / _analyze_article, which calls
the LLM and market data) runs via asyncio.to_thread; only the DB writes touch the loop.
A source that throws degrades to WARN and is recorded — it never crashes the worker.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import uuid

import asyncpg

from finscrape.logging_config import correlation_id
from finscrape.market_data import get_market_data
from finscrape.pipeline import FinScrapePipeline
from server.ai import analyze_event
from server.alert_rules import fire_alerts
from server.correlate import (
    VELOCITY_WINDOW_DAYS,
    Market,
    NewsItem,
    Prediction,
    analyze_correlations,
    extract_topics,
    watch_symbols,
)
from server.geocode import geocode_event
from server.ingest import canonical_url, ingest_events
from server.obs import record_ingest
from server.pubsub import publish
from server.queries import get_event_by_id, get_recent_predictions, save_ai_cache
from server.routes.telegram import notify_new_events
from server.settings import get_settings
from worker.health import (
    finish_scrape_run,
    forget_retired_sources,
    record_feed_health,
    record_source_health,
    start_scrape_run,
)
from worker.sources import Item, build_enrichers, build_sources

log = logging.getLogger("worldfin.worker")

_TIERS = {"wire", "gov", "intel", "mainstream", "market", "tech", "other"}


async def persist_correlations(pool: asyncpg.Pool, signals: list) -> None:
    """Write correlation signals to the correlations table (one row each)."""
    for sig in signals:
        await pool.execute(
            "INSERT INTO correlations (dedupe_key, signal_type, confidence, payload) "
            "VALUES ($1, $2, $3, $4) ON CONFLICT (dedupe_key) DO UPDATE SET "
            "confidence = EXCLUDED.confidence, payload = EXCLUDED.payload, "
            "detected_at = now()",
            sig.dedupe_key,
            sig.type,
            sig.confidence,
            {"id": sig.id, "value": sig.value, **sig.payload},
        )


def _visit_key(url: str) -> str:
    """Canonical URL, or "" for placeholders like `ingestor://usgs` that every
    URL-less item from a source shares — marking one would silence the source."""
    return canonical_url(url) if url.startswith(("http://", "https://")) else ""


async def unvisited(pool: asyncpg.Pool, items: list[Item]) -> list[Item]:
    """Drop items whose URL an earlier cycle judged or an earlier item repeats."""
    urls = [_visit_key(a.url) for a, _ in items]
    seen = {
        r["url"]
        for r in await pool.fetch(
            "SELECT url FROM visited_urls WHERE url = ANY($1::text[])", urls
        )
    }
    kept = []
    for item, url in zip(items, urls):
        if not url or url not in seen:
            kept.append(item)
            if url:
                seen.add(url)
    return kept


async def mark_visited(pool: asyncpg.Pool, source: str, urls: list[str]) -> None:
    canon = [u for u in (_visit_key(x) for x in urls) if u]
    if canon:
        await pool.execute(
            "INSERT INTO visited_urls (url, source) SELECT u, $2 FROM unnest($1::text[]) u "
            "ON CONFLICT (url) DO NOTHING",
            canon,
            source,
        )


async def store_analysis(pool: asyncpg.Pool, event_ids: list[int]) -> int:
    """Analyse events and store the answers the API serves on click.

    The API host is refused by the analysis provider while GitHub runners are not, so the
    API hands a click it cannot answer to worker.analyze_event. Returns rows stored.
    """
    model = get_settings().ai_model
    stored = 0
    for eid in event_ids:
        try:
            event = await get_event_by_id(pool, eid)
            if not event:
                continue
            result = await asyncio.to_thread(analyze_event, event)
            if result.get("heuristic"):
                continue
            key = hashlib.sha256(f"{model}:{eid}".encode()).hexdigest()
            await save_ai_cache(pool, key, eid, result)
            stored += 1
        except Exception:  # one event's failure spares the rest
            log.warning("analysis failed for event %s", eid, exc_info=True)
    return stored


async def merge_coverage(
    pool: asyncpg.Pool, merges: list[tuple[str, str, str]]
) -> list[tuple[str, str, str]]:
    """Apply the pipeline's same-story merges (subject, url, source) to Postgres and
    return the ones whose row does not exist yet.

    The target is found by its exact subject: the pipeline only collapses whitespace,
    and ingest writes the subject as given. Sources ingest concurrently, so a merge can
    point at an event another source has accepted but not written yet.
    """
    missed = []
    for merge in merges:
        status = await pool.execute(
            """
            UPDATE events SET
              articles = CASE WHEN articles ? $2 THEN articles
                              ELSE articles || to_jsonb($2::text) END,
              sources  = CASE WHEN sources ? $3 THEN sources
                              ELSE sources || to_jsonb($3::text) END
            WHERE id = (SELECT id FROM events WHERE subject = $1 ORDER BY id DESC LIMIT 1)
            """,
            *merge,
        )
        if status == "UPDATE 0":
            missed.append(merge)
    return missed


class PostgresEvents:
    """The pipeline's dedup window, read from Postgres instead of its SQLite file.

    The pipeline runs in a worker thread, so reads hop onto the event loop that owns
    the pool. Events the pipeline accepts wait in `pending` until the cycle ingests
    them; merges into any row are applied by `merge_coverage`, keyed by subject.
    """

    _RECENT = (
        "SELECT id, subject, event_type, tickers, sources, articles "
        "FROM events ORDER BY id DESC LIMIT 100"
    )

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool
        self.loop = asyncio.get_running_loop()
        self.pending: list[dict] = []
        self._lock = threading.Lock()

    @property
    def events(self) -> list[dict]:
        rows = asyncio.run_coroutine_threadsafe(
            self.pool.fetch(self._RECENT), self.loop
        ).result()
        stored = [
            {
                **dict(r),
                **{k: _json_list(r[k]) for k in ("tickers", "sources", "articles")},
            }
            for r in rows
        ]
        subjects = {e["subject"] for e in stored}
        with self._lock:
            # Once ingested, a pending event is read back from Postgres instead.
            self.pending = [e for e in self.pending if e["subject"] not in subjects][
                -100:
            ]
            return list(reversed(stored)) + self.pending

    def add_event(self, event: dict) -> int:
        with self._lock:
            self.pending.append(event)
        return 0

    def update_event(self, event_id: int, **fields) -> None:
        pass  # merge_coverage writes the merge once the cycle ingests


def _json_list(value) -> list:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


async def prune_old_rows(pool: asyncpg.Pool, days: int, event_days: int = 0) -> None:
    """Age out operational tables, and events (with their scored outcomes, which cascade)
    once older than event_days; 0 keeps events forever."""
    if event_days > 0:
        await pool.execute(
            "DELETE FROM events WHERE timestamp < now() - make_interval(days => $1)", event_days
        )
    if days <= 0:
        return
    for table, column in (
        ("correlations", "detected_at"),
        ("scrape_runs", "started_at"),
        ("ai_analysis_cache", "created_at"),
        ("visited_urls", "visited_at"),
        ("alert_history", "fired_at"),
    ):
        await pool.execute(
            f"DELETE FROM {table} WHERE {column} < now() - make_interval(days => $1)",
            days,
        )


async def evict_to_size(pool: asyncpg.Pool, max_mb: float) -> int:
    """Keep the database under max_mb by dropping the oldest events (and their outcomes) in
    batches of 5%, compacting after each so the size really falls. Returns events removed."""
    removed = 0
    for _ in range(10):
        size = await pool.fetchval("SELECT pg_database_size(current_database())")
        if size <= max_mb * 1e6:
            break
        batch = await pool.fetchval("SELECT GREATEST(1, count(*) / 20) FROM events")
        n = await pool.fetchval(
            "WITH gone AS (DELETE FROM events WHERE id IN "
            "(SELECT id FROM events ORDER BY timestamp LIMIT $1) RETURNING 1) "
            "SELECT count(*) FROM gone",
            batch,
        )
        if not n:
            break
        removed += n
        await pool.execute("VACUUM FULL events")
    return removed


def _source_type(source: str) -> str:
    """Tier is encoded as the suffix after ':' in our source tags (world/<feed>:<tier>,
    gdelt/<domain>:wire, usgs_quakes:gov, …)."""
    tail = (source or "").rsplit(":", 1)[-1]
    return tail if tail in _TIERS else "other"


def velocity_history(rows: list, now: float, window_hours: int) -> dict[str, list[int]]:
    """Topic mention counts for each of the windows before the current one, oldest
    first, from (subject, source, epoch seconds) rows. Quiet windows count as 0."""
    width = window_hours * 3600
    windows = max(1, VELOCITY_WINDOW_DAYS * 24 // window_hours)
    buckets: list[list[NewsItem]] = [[] for _ in range(windows)]
    for subject, source, ts in rows:
        i = int((now - ts) // width) - 1
        if 0 <= i < windows:
            buckets[i].append(NewsItem(title=subject, link="", source=source))
    counts = [extract_topics(b) for b in reversed(buckets)]
    return {
        topic: [c.get(topic, {}).get("velocity", 0) for c in counts]
        for topic in {t for c in counts for t in c}
    }


class Worker:
    def __init__(self, pool: asyncpg.Pool, max_articles: int = 20):
        self.pool = pool
        self.max_articles = max_articles
        self.sources = build_sources(max_articles)
        self.enrichers = build_enrichers()
        self.pipeline = FinScrapePipeline(PostgresEvents(pool))
        self._unmerged: list[tuple[str, str, str]] = []

    def _analyze_blocking(
        self, source_name: str, items: list[Item]
    ) -> tuple[list[dict], list[tuple[str, str, str]], list[str]]:
        """Thread body: articles -> (ingest dicts, same-story merges, judged URLs).

        An article the LLM never answered for is left out of the judged URLs so the
        next cycle retries it instead of losing it.
        """
        dicts: list[dict] = []
        merges: list[tuple[str, str, str]] = []
        judged: list[str] = []
        enrich = self.enrichers.get(source_name)
        for article, geo in items:
            try:
                if enrich:
                    article = enrich(article)
                # The article's tag carries the tier correlation types read.
                tag = article.source or source_name
                fe = self.pipeline._analyze_article(tag, article)
            except Exception as exc:  # noqa: BLE001 - one bad article must not end the cycle
                log.warning("[%s] analyze failed: %s", source_name, exc)
                continue
            if not self.pipeline.ai_failed():
                judged.append(article.url)
            if fe is None:
                matched = self.pipeline.merged_into()
                if matched and matched.get("subject"):
                    merges.append((matched["subject"], article.url, tag))
                continue
            d = fe.to_dict()
            lat, lon = geocode_event(
                fe.subject, fe.affected_entities, explicit_latlon=geo
            )
            d["lat"], d["lon"] = lat, lon
            dicts.append(d)
        return dicts, merges, judged

    async def run_source(self, name: str) -> dict:
        """Run one source end to end. Returns the ingest result (or zeros on failure)."""
        correlation_id.set(uuid.uuid4().hex[:16])  # one id per cycle → traceable logs
        run_id = await start_scrape_run(self.pool, name)
        try:
            items = await asyncio.to_thread(self.sources[name])
            fresh = (await unvisited(self.pool, items))[: self.max_articles]
            dicts, merges, judged = await asyncio.to_thread(
                self._analyze_blocking, name, fresh
            )
            result = await ingest_events(self.pool, dicts)
            await self._merge(merges)
            await mark_visited(self.pool, name, judged)
            status = "OK" if items else "EMPTY"
            await record_source_health(self.pool, name, len(items), status)
            if feeds := getattr(self.sources[name], "feed_health", None):
                await record_feed_health(self.pool, feeds)
            await finish_scrape_run(self.pool, run_id, "ok", result["inserted"])
            record_ingest(name, result["inserted"], result["duplicates"], status)
            if result["inserted_ids"]:
                await fire_alerts(self.pool, result["inserted_rows"])
                await notify_new_events(result["inserted_rows"])
                # Push to API WS clients across processes (no-op unless Redis enabled).
                await publish(
                    {
                        "type": "new_events",
                        "source": name,
                        "count": result["inserted"],
                        "events": result["inserted_rows"],
                    }
                )
            log.info(
                "[%s] %d fetched, %d inserted, %d dup",
                name,
                len(items),
                result["inserted"],
                result["duplicates"],
            )
            return result
        except Exception as exc:
            log.exception("[%s] cycle failed", name)
            await record_source_health(self.pool, name, 0, "WARN", str(exc))
            await finish_scrape_run(self.pool, run_id, "failed", 0)
            record_ingest(name, 0, 0, "WARN")
            return {
                "inserted": 0,
                "duplicates": 0,
                "inserted_ids": [],
                "inserted_rows": [],
            }

    async def run_all_once(self) -> None:
        """Run every source once concurrently (startup warm-up), then correlate."""
        await forget_retired_sources(self.pool, list(self.sources))
        await asyncio.gather(
            *(self.run_source(n) for n in self.sources),
            return_exceptions=True,
        )
        await self._merge([])
        if self._unmerged:
            log.warning("%d merges found no event", len(self._unmerged))
            self._unmerged = []
        await self.run_correlations()

    async def _merge(self, merges: list[tuple[str, str, str]]) -> None:
        """Apply merges plus earlier ones whose event had not been written yet."""
        pending, self._unmerged = self._unmerged, []
        self._unmerged.extend(await merge_coverage(self.pool, pending + merges))

    async def run_backtest(self) -> int:
        """Score matured directional verdicts against the price move in the window
        after each event (Phase 7), then fill the +2 / +4 day vs-SPY columns of calls
        whose windows have closed. Returns rows written or updated."""
        from finscrape.market_data import event_excess, event_moves
        from server.accuracy import backtest, score_vs_spy

        return await backtest(self.pool, event_moves) + await score_vs_spy(
            self.pool, event_excess
        )

    async def _recent_markets(self, lookback_hours: int) -> list[Market]:
        """Price moves for the most-mentioned recent tickers plus the fixed watch list →
        feeds detect_market. Tickers picked from the news always have coverage, so only
        the watch list can show a silent move. Market fetch is cached + batched
        (finscrape.market_data) and runs off the event loop."""
        rows = await self.pool.fetch(
            "SELECT jsonb_array_elements_text(tickers) AS t, count(*) AS c FROM events "
            "WHERE timestamp >= now() - ($1 || ' hours')::interval "
            "AND jsonb_array_length(tickers) > 0 "
            "GROUP BY t ORDER BY c DESC LIMIT 25",
            str(lookback_hours),
        )
        tickers = list(
            dict.fromkeys([*(r["t"] for r in rows if r["t"]), *watch_symbols()])
        )
        data = await asyncio.to_thread(get_market_data, tickers)
        return [
            Market(symbol=d["ticker"], change=float(d.get("change_percent", 0.0)))
            for d in data
            if isinstance(d, dict) and d.get("ticker")
        ]

    async def run_correlations(self, lookback_hours: int = 24) -> int:
        """Cluster recent events + flag corroboration/divergence; persist signals.
        Returns count."""
        if not get_settings().enable_correlation:
            return 0
        rows = await self.pool.fetch(
            "SELECT subject, sources, articles, tickers, timestamp, lat, lon FROM events "
            "WHERE timestamp >= now() - ($1 || ' hours')::interval",
            str(lookback_hours),
        )
        items = [
            NewsItem(
                title=r["subject"],
                link=(r["articles"][0] if r["articles"] else r["subject"]),
                source=(r["sources"][0] if r["sources"] else ""),
                source_type=_source_type(r["sources"][0] if r["sources"] else ""),
                lat=r["lat"],
                lon=r["lon"],
                timestamp=r["timestamp"].timestamp(),
                tickers=tuple(_json_list(r["tickers"])),
            )
            for r in rows
        ]
        markets = await self._recent_markets(lookback_hours)
        # State comes from Postgres: a `--once` run is a fresh process with no memory.
        seen = {
            r["dedupe_key"]
            for r in await self.pool.fetch(
                "SELECT dedupe_key FROM correlations "
                "WHERE detected_at >= now() - ($1 || ' hours')::interval",
                str(lookback_hours),
            )
        }
        signals, _ = analyze_correlations(
            items,
            markets=markets,
            predictions=await self._recent_predictions(lookback_hours),
            prev_snapshot={},
            seen=seen,
            velocity_history=await self._velocity_history(lookback_hours),
        )
        await persist_correlations(self.pool, signals)
        if signals:
            log.info("correlations: emitted %d signals", len(signals))
        return len(signals)

    async def _recent_predictions(self, lookback_hours: int) -> list[Prediction]:
        """AI-estimated moves for recently analysed events → detect_prediction_leads_news.

        Best-effort: only events that were actually analysed have a cached estimate, so
        a quiet window simply yields no predictions.
        """
        strongest = await get_recent_predictions(self.pool, lookback_hours)
        return [Prediction(symbol=sym, shift=shift) for sym, shift in strongest.items()]

    async def _velocity_history(self, lookback_hours: int) -> dict[str, list[int]]:
        rows = await self.pool.fetch(
            "SELECT subject, sources->>0 AS source, extract(epoch FROM timestamp) AS ts, "
            "extract(epoch FROM now()) AS now FROM events "
            "WHERE timestamp >= now() - ($1 || ' hours')::interval",
            str(VELOCITY_WINDOW_DAYS * 24 + lookback_hours),
        )
        if not rows:
            return {}
        now = float(rows[0]["now"])
        return velocity_history(
            [(r["subject"], r["source"] or "", float(r["ts"])) for r in rows],
            now,
            lookback_hours,
        )
