"""Event clustering into storylines.

The same story from five sources currently produces five feed rows. This module
greedily groups events whose subject embeddings are similar *and* that happened
close in time into one storyline, so the feed can collapse the members under a
single top row.

Design:
- `cluster_events` is pure: it takes a `similarity(subject_a, subject_b)` callable,
  so tests can inject fake embeddings (no network, no Ollama).
- `build_storylines` wires it to `finscrape.analysis.embeddings`. Where Ollama is
  unreachable (the Render API has none) it falls back to `same_story`: shared
  tickers plus word overlap in the subjects.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Callable

# Cosine threshold for two subjects to be treated as the same storyline.
DEFAULT_THRESHOLD = 0.75

# Events further apart than this never merge, even with high similarity
# (same phrase re-appearing months later is a new story, not a continuation).
DEFAULT_WINDOW_HOURS = 48


# Tuned on 200 production events (12 Oct 2026): it grouped repeat missile tests, strikes
# on one airport and a ceasefire's follow-ups, and kept unrelated stories apart.
LEXICAL_OVERLAP = 0.5
_STOP = frozenset(
    "the and for with from into over after amid says said will its their new more than "
    "about against report".split()
)


def subject_words(subject: str) -> frozenset[str]:
    """Content words of a headline, lowercased, with a plural 's' trimmed."""
    words = set()
    for w in re.findall(r"[a-z0-9]+", subject.lower()):
        if len(w) < 3 or w in _STOP:
            continue
        words.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return frozenset(words)


def same_story(a: dict, b: dict) -> bool:
    """Embedding-free match: the events share a ticker, and at least two content words
    making up half of the shorter headline."""
    if not set(a.get("tickers") or []) & set(b.get("tickers") or []):
        return False
    wa = subject_words(a.get("subject") or "")
    wb = subject_words(b.get("subject") or "")
    shared = len(wa & wb)
    return shared >= 2 and shared / min(len(wa), len(wb)) >= LEXICAL_OVERLAP


def _parse_ts(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _within_window(a: str | None, b: str | None, window_hours: int) -> bool:
    """True when both timestamps parse and differ by at most window_hours."""
    ta, tb = _parse_ts(a), _parse_ts(b)
    if ta is None or tb is None:
        return True  # unknown times never block a merge (best effort)
    return abs((ta - tb).total_seconds()) <= window_hours * 3600


def cluster_meta(members: list[dict]) -> dict:
    """Aggregate one cluster's metadata: member ids, ticker/source/article unions,
    avg score, first-seen time and the newest subject (the feed's top row)."""
    ordered = sorted(members, key=lambda e: e.get("created_at") or "")
    tickers: list[str] = []
    seen_t: set[str] = set()
    sources: list[str] = []
    seen_s: set[str] = set()
    articles: set[str] = set()
    for m in ordered:
        for t in m.get("tickers") or []:
            if t not in seen_t:
                seen_t.add(t)
                tickers.append(t)
        for s in m.get("sources") or []:
            if s not in seen_s:
                seen_s.add(s)
                sources.append(s)
        articles.update(str(a) for a in m.get("articles") or [])
    scores = [float(m.get("signal_score") or 0) for m in ordered]
    return {
        "member_ids": [m.get("id") for m in ordered],
        "size": len(ordered),
        "tickers": tickers[:10],
        "sources": sources,
        # Distinct reports behind the cluster. The pipeline merges same-story
        # coverage into one event before storage, so member count is ~always 1
        # and this is the only place corroboration survives.
        "reports": max(len(articles), len(ordered)),
        "avg_score": round(sum(scores) / len(scores), 2) if scores else 0.0,
        "first_seen": ordered[0].get("created_at"),
        "top_subject": ordered[-1].get("subject") or "",
    }


def cluster_events(
    events: list[dict],
    similarity: Callable[[str, str], float | None],
    threshold: float = DEFAULT_THRESHOLD,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> list[dict]:
    """Greedy single-pass clustering.

    Events are processed oldest-first for determinism. Each event joins the
    first cluster whose *seed* is within `window_hours` and whose subject is
    `threshold`-similar to the seed's subject; otherwise it seeds a new cluster.
    A similarity of None (embeddings unavailable) always starts a new cluster —
    i.e. singletons, the feed's unchanged shape.

    Returns cluster dicts (metadata only, use `build_storylines` for the
    full-member form the API serves), sorted by member count desc.
    """
    ordered = sorted(events, key=lambda e: e.get("created_at") or "")
    clusters: list[dict] = []  # {"seed_subject", "seed_ts", "members"}
    for ev in ordered:
        subject = ev.get("subject") or ""
        placed = False
        for cl in clusters:
            if not _within_window(cl["seed_ts"], ev.get("created_at"), window_hours):
                continue  # seeds only get older as we walk; once stale, always stale
            score = similarity(subject, cl["seed_subject"])
            if score is not None and score >= threshold:
                cl["members"].append(ev)
                placed = True
                break
        if not placed:
            clusters.append(
                {
                    "seed_subject": subject,
                    "seed_ts": ev.get("created_at"),
                    "members": [ev],
                }
            )

    metas = [cluster_meta(cl["members"]) for cl in clusters]
    metas.sort(key=lambda c: (c["size"], c["first_seen"] or ""), reverse=True)
    return metas


# Ollama serves concurrent /api/embeddings requests well, and a cold process
# embedding ~200 subjects serially (~0.4-2s each) would stall /api/storylines
# for minutes. Prefetch the per-subject vectors in a small thread pool — the
# clustering itself stays a pure cosine comparison over cached vectors.
_PREFETCH_WORKERS = 6


def build_storylines(
    events: list[dict], threshold: float = DEFAULT_THRESHOLD
) -> list[dict]:
    """Production wiring: cluster full event rows with the local embeddings.

    Each returned cluster carries `members` (the full event dicts, newest
    first) so the feed can render the top row and expand the rest. When
    Ollama is unreachable, `same_story` decides instead.
    """
    from concurrent.futures import ThreadPoolExecutor

    from finscrape.analysis import embeddings

    subjects = list(dict.fromkeys((e.get("subject") or "") for e in events))
    vectors: dict[str, tuple[float, ...] | None] = {}
    try:
        with ThreadPoolExecutor(max_workers=_PREFETCH_WORKERS) as pool:
            for sub, vec in zip(subjects, pool.map(embeddings.embed, subjects)):
                vectors[sub] = vec
    except Exception:
        vectors = {}  # never fatal: fall through to per-call embed (or None)

    by_subject = {e.get("subject") or "": e for e in events}

    def similarity(a: str, b: str) -> float | None:
        va = vectors[a] if a in vectors else embeddings.embed(a)
        vb = vectors[b] if b in vectors else embeddings.embed(b)
        cosine = embeddings.cosine(va, vb)
        if cosine is not None:
            return cosine
        return 1.0 if same_story(by_subject[a], by_subject[b]) else 0.0

    metas = cluster_events(events, similarity, threshold=threshold)
    member_by_id = {e.get("id"): e for e in events}
    out = []
    for meta in metas:
        members = [
            member_by_id[mid] for mid in meta["member_ids"] if mid in member_by_id
        ]
        members.sort(key=lambda e: e.get("created_at") or "")
        cluster = dict(meta)
        cluster["members"] = list(reversed(members))  # newest first for the feed
        out.append(cluster)
    return out
