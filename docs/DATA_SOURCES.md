# WorldFin — Data Sources

Every external source WorldFin pulls, its access terms, and key status. All sources are
**keyless** (ReliefWeb needs a free approved app name, not a key). Source of truth in code:
`finscrape/scrapers/world/feeds.py` and `finscrape/ingestors/`.

## License & compliance

worldmonitor.app (AGPL-3.0) is **never** copied into this repo — we use only
non-copyrightable **facts** (public feed URLs, country/crypto JSON) and **independently
reimplement** algorithms (clustering, correlation: `server/correlate.py`). fin-scrape stays MIT.

## World / geopolitics RSS feeds

Seed registry (`finscrape/scrapers/world/feeds.py`). `tier` ∈ wire/gov/intel/mainstream/market;
`risk` = propaganda risk used for trust weighting. Public RSS endpoints; classification is ours.
The table is a representative subset of the 32 registered feeds; `/api/feeds` lists them all.

| key | source | tier | risk | endpoint |
|---|---|---|---|---|
| ecb_press | ECB Press | gov | low | www.ecb.europa.eu/rss/press.html |
| eu_commission | European Commission | gov | low | ec.europa.eu/commission/presscorner/api/rss?language=en |
| fed_press | Federal Reserve Press | gov | low | www.federalreserve.gov/feeds/press_all.xml |
| un_news | UN News | gov | low | news.un.org/feed/subscribe/en/news/all/rss.xml |
| defense_one | Defense One | intel | low | www.defenseone.com/rss/all/ |
| war_on_the_rocks | War on the Rocks | intel | low | warontherocks.com/feed/ |
| aljazeera | Al Jazeera | mainstream | medium | www.aljazeera.com/xml/rss/all.xml |
| bbc_world | BBC World | mainstream | low | feeds.bbci.co.uk/news/world/rss.xml |
| dw_world | Deutsche Welle | mainstream | low | rss.dw.com/rdf/rss-en-world |
| france24 | France 24 | mainstream | low | www.france24.com/en/rss |
| guardian_world | The Guardian World | mainstream | low | www.theguardian.com/world/rss |
| npr_world | NPR World | mainstream | low | feeds.npr.org/1004/rss.xml |
| scmp_news | South China Morning Post | mainstream | medium | www.scmp.com/rss/91/feed |
| times_of_israel | The Times of Israel | mainstream | medium | www.timesofisrael.com/feed/ (blocks GitHub runners; works locally) |
| cnbc_finance | CNBC Finance | market | low | search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100 |
| cnbc_world | CNBC World | market | low | www.cnbc.com/id/100727362/device/rss/rss.html |
| economist_finance | The Economist — Finance & Economics | market | low | www.economist.com/finance-and-economics/rss.xml |
| ft_world | Financial Times World | market | low | www.ft.com/world?format=rss |
| marketwatch_top | MarketWatch Top Stories | market | low | feeds.content.dowjones.io/public/rss/mw_topstories |
| ap_gnews | Associated Press (via Google News) | wire | low | news.google.com/rss/search?q=when:24h+source:%22Associated+Press%22&hl |
| reuters_world_gnews | Reuters (world, via Google News) | wire | low | news.google.com/rss/search?q=when:24h+source:reuters+world&hl=en-US&gl |

> Reuters/AP are pulled via Google News RSS search because their direct RSS is gated — the
> aggregator URL is a public fact. Respect each outlet's terms for downstream redistribution.

## Keyless free-API ingestors

`finscrape/ingestors/`. Network `fetch` is separate from pure `parse` (parsers unit-tested
against fixtures). All no-auth.

| ingestor | role | endpoint | notes |
|---|---|---|---|
| `usgs_quakes` | earthquakes (event) | earthquake.usgs.gov/.../summary/4.5_week.geojson | carries exact lat/lon; M4.5+ filter |
| `gdelt` | global news (event) | data.gdeltproject.org/gdeltv2/lastupdate.txt | the 15-minute events export (not the rate-limited DOC API); titles from URL slugs, kept only when the entity map ties them to a sector |
| `reliefweb` | disasters (event) | api.reliefweb.int/v2/disasters | live since 30 Sep 2026 with an approved `RELIEFWEB_APPNAME`; only disasters under 2 hours old pass the freshness gate |
| `coingecko` | crypto movers | api.coingecko.com/api/v3/coins/markets | **not registered**: crypto was dropped from the event mix; the class stays for reuse |
| `opensky` | live flights (data layer) | opensky-network.org/api/states/all | NOT an event source; `parse_states` only |

### Terms notes
- **USGS** — US Government public domain.
- **GDELT** — free and open. The DOC API answered 429 to most requests at any interval, so
  the ingestor reads the static 15-minute export files instead, which have no rate limit.
- **ReliefWeb** — v1 is decommissioned (410); v2 needs an approved `appname`
  (https://apidoc.reliefweb.int/parameters#appname). Production reads it from the repo
  variable `RELIEFWEB_APPNAME`; without it the source stays off.
- **CoinGecko** — public/demo tier; rate-limited. Not in the event mix.
- **OpenSky** — anonymous access is rate-limited and time-resolution-limited; a flights layer,
  not a market signal.

## Key status

All sources above are **keyless**. The keys in the system are the **LLM** backend
(`OPENAI_API_KEY` for `OPENAI_BASE_URL`, or local Ollama) and the ingest `FINSCRAPE_API_KEY`
(auth for mutating `/api` routes) — see `.env.example`.

Social: Reddit posts for the sentiment panel come from one Reddit RSS fetch per ingest run
(`worker/social.py`); Reddit's JSON API and StockTwits answer 403, and RSS repeats the same
100 posts across runs, so sentiment fills slowly.

## Adding a source

**An RSS/Atom feed** — one entry in `finscrape/scrapers/world/feeds.py`:

```python
Feed(
    "ecb_press",                                  # key: unique, stable, becomes the source tag
    "https://www.ecb.europa.eu/rss/press.html",
    "ECB Press",
    "gov",                                        # tier: wire|gov|intel|mainstream|market|tech|other
    region="europe",
    propaganda_risk="low",                        # feeds source trust weighting
    topics=("monetary", "economy"),
)
```

That single entry wires everything: `WorldRSSScraper` reads `feed_urls()`, so the worker
starts pulling it next cycle; `/api/feeds` lists it for the source picker; `/api/rss-proxy`
will proxy it (the registry *is* the SSRF allowlist — an unknown key is a 400); and the
`tier` becomes the `source_type` the correlation engine scores.

Validate before adding. HTTP 200 is not enough — CSIS served 200 for a feed whose newest
item was from March 2016:

```python
r = requests.get(url, headers={"User-Agent": "finscrape-worldfin/0.1"}, timeout=25)
d = feedparser.parse(r.content)
assert r.status_code == 200 and d.entries          # reachable and non-empty
assert d.entries[0].get("published_parsed")        # dated, so staleness is detectable
```

Check the newest item is days old, not years. `tests/test_world_phase2.py` guards the
structural invariants (unique keys and URLs, valid tier/risk, https); liveness is a
network property and belongs in a probe, not the suite.

**A structured JSON API** — subclass `BaseIngestor` in `finscrape/ingestors/`, implement
the pure `parse`, and add the class to `EVENT_INGESTORS`. `fetch_raw` already handles
timeouts, retries and backoff. Carry `lat`/`lon` on the `RawGeoEvent` when the source
knows them (USGS does) — otherwise `server.geocode` infers a country centroid from the
text, which is much coarser.

**Tier matters more than count.** `detect_convergence` needs one story confirmed by three
*distinct* source types within an hour, so a fourth mainstream outlet adds far less than
the first primary source in a tier you do not yet cover.
