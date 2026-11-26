# FinScrape — Data Sources

Every external source FinScrape pulls, its access terms, and key status. All sources are
**keyless** (ReliefWeb needs a free approved app name, not a key). Source of truth in code:
`finscrape/fetchers/world/feeds.py` and `finscrape/ingestors/`.

## License & compliance

worldmonitor.app (AGPL-3.0) is **never** copied into this repo — we use only
non-copyrightable **facts** (public feed URLs, country/crypto JSON) and **independently
reimplement** algorithms (clustering, correlation: `server/correlate.py`). fin-scrape stays MIT.

## World / geopolitics RSS feeds

Seed registry (`finscrape/scrapers/world/feeds.py`). `tier` ∈ wire/gov/intel/mainstream/market;
`risk` = propaganda risk used for trust weighting. Public RSS endpoints; classification is ours.
The table is a representative subset of the 37 registered feeds; `/api/feeds` lists them all.

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
| cnbc_finance | CNBC Finance | market | low | search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100 |
| cnbc_world | CNBC World | market | low | www.cnbc.com/id/100727362/device/rss/rss.html |
| economist_finance | The Economist — Finance & Economics | market | low | www.economist.com/finance-and-economics/rss.xml |
| ft_world | Financial Times World | market | low | www.ft.com/world?format=rss |
| marketwatch_top | MarketWatch Top Stories | market | low | feeds.content.dowjones.io/public/rss/mw_topstories |
| foreign_policy | Foreign Policy | intel | low | foreignpolicy.com/feed/ |
| the_diplomat | The Diplomat | intel | low | thediplomat.com/feed/ |
| al_monitor | Al-Monitor | intel | low | www.al-monitor.com/rss |
| crisis_group | International Crisis Group | intel | low | www.crisisgroup.org/rss |
| atlantic_council | Atlantic Council | intel | low | www.atlanticcouncil.org/feed/ |
| ecfr | European Council on Foreign Relations | intel | low | www.ecfr.eu/rss |
| ap_gnews | Associated Press (via Google News) | wire | low | news.google.com/rss/search?q=when:24h+source:%22Associated+Press%22&hl |
| reuters_world_gnews | Reuters (world, via Google News) | wire | low | news.google.com/rss/search?q=when:24h+source:reuters+world&hl=en-US&gl |

> Reuters/AP are pulled via Google News RSS search because their direct RSS is gated — the
> aggregator URL is a public fact. Respect each outlet's terms for downstream redistribution.

## Keyless free-API ingestors

`finscrape/ingestors/`. Network `fetch` is separate from pure `parse` (parsers unit-tested
against fixtures). All no-auth.

| ingestor | role | endpoint | notes |
|---|---|---|---|
| `usgs_quakes` | earthquakes (event) | earthquake.usgs.gov/.../summary/4.5_day.geojson | carries exact lat/lon; M4.5+ filter, capped at 8 per cycle so quakes stay a minority source |
| `gdelt` | global news (event) | data.gdeltproject.org/gdeltv2/lastupdate.txt | the 15-minute events export (not the rate-limited DOC API); titles from URL slugs, kept only when the entity map ties them to a sector; if the listed export is not downloadable yet, walks back up to 2 hours |
| `reliefweb` | disasters (event) | api.reliefweb.int/v2/disasters | live since 30 Sep 2026 with an approved `RELIEFWEB_APPNAME`; newest 8 per cycle, so disasters inform rather than dominate the feed |
| `coingecko` | crypto movers | api.coingecko.com/api/v3/coins/markets | **not registered**: crypto was dropped from the event mix; the class stays for reuse |
| `opensky` | live flights (data layer) | opensky-network.org/api/states/all | NOT an event source; `parse_states` only |

## Licensing review

Reviewed 2026-11-26 against each provider's published terms. This is an engineering record,
not legal advice; a commercial launch re-checks every row with counsel. The rule for all
sources is the same: FinScrape stores the **headline, canonical URL, source, timestamp and a
short analysis excerpt**, never a full-text archive, and shows the source on every event.

| Source family | Published terms | Allowed use here | Commercial use | Terms link |
|---|---|---|---|---|
| RSS/Atom outlets in the registry (37 feeds) | each publisher's own feed terms; a feed is a distribution format, not a licence to the article | fetch the feed, store headline/link/short excerpt, attribute the outlet and link back; do not republish the article body | per publisher; some allow with attribution, others (FT, Reuters direct) require a licence | the outlet's own `/terms` page; registry entry names the outlet |
| Reuters / AP via Google News RSS | Google News feed terms: personal, non-commercial use only; do not redistribute the feed; attribute Google News and the provider, link to the item | read for non-commercial monitoring only | **not permitted**; replace with Reuters Connect, AP Content Services or GDELT before monetising | https://www.google.com/intl/en_us/news_feed_terms.html |
| GDELT 2.0 events export | free and open for academic, commercial and government use; no fee; redistribution allowed with citation | read the 15-minute export, keep derived event rows | yes, with the required citation and link | https://www.gdeltproject.org/about.html#termsofuse |
| ReliefWeb v2 disasters | site terms: personal, non-commercial, no resale/redistribution/compilation/derivatives; partner content may be copyrighted; 1,000 calls/day per appname | read disaster records, keep derived facts (name, type, country, date), attribute ReliefWeb; do not republish report text | **requires permission**; keep the source off for a commercial product until OCHA agrees | https://reliefweb.int/terms-conditions |
| USGS earthquake feed | US Government work, public domain | read, store and display with courtesy attribution | yes | https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits |
| OpenSky states | non-profit research/education only; operational or commercial use needs a written licence; attribution required | data layer only, not an event source | **licence required**; disable or license before commercial launch | https://opensky-network.org/about/terms-of-use |
| CoinGecko markets | public/demo tier, rate-limited, attribution | not in the event mix | check the current plan before use | https://www.coingecko.com/en/api |
| Reddit RSS (sentiment) | Reddit terms and user content; no commercial reuse without permission | headline/link for sentiment counts | permission required | https://www.redditinc.com/policies/user-agreement |

**Allowed-use policy**

- Store only what the event needs: headline, URL, source key, timestamp, and the short excerpt
  the analyser reads. The event row caps that excerpt at 600 characters; it is not a copy of
  the article and must not become one.
- Always show the source and link out. A row without a source is a bug, not an anonymous fact.
- Honour a removal request by deleting the row and its excerpt; the URL is the identifier.
- A new feed is not added until its row here says what may be stored and whether commercial
  use is allowed.
- **Owner decision before any paid tier:** replace the Google News RSS rows (Reuters/AP) with a
  licensed feed and either obtain ReliefWeb permission or drop it. Both are non-commercial
  today; neither blocks the free demo.

### Operational notes
- **USGS** - US Government public domain; the ingestor filters M4.5+ and caps at 8 per cycle.
- **GDELT** - the DOC API answered 429 to most requests at any interval, so the ingestor reads
  the static 15-minute export files instead, which have no rate limit.
- **ReliefWeb** - v1 is decommissioned (410); v2 needs an approved `appname`
  (https://apidoc.reliefweb.int/parameters#appname). Production reads it from the repo
  variable `RELIEFWEB_APPNAME`; without it the source stays off.
- **CoinGecko** - public/demo tier; rate-limited. Not in the event mix.
- **OpenSky** - anonymous access is rate-limited and time-resolution-limited; a flights layer,
  not a market signal.

## Key status

All sources above are **keyless**. The keys in the system are the **LLM** backend
(`OPENAI_API_KEY` for `OPENAI_BASE_URL`, or local Ollama) and the ingest `FINSCRAPE_API_KEY`
(auth for mutating `/api` routes) — see `.env.example`.

Social: Reddit posts for the sentiment panel come from one Reddit RSS fetch per ingest run
(`worker/social.py`); Reddit's JSON API and StockTwits answer 403, and RSS repeats the same
100 posts across runs, so sentiment fills slowly.

## Adding a source

**An RSS/Atom feed** — one entry in `finscrape/fetchers/world/feeds.py`:

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
starts pulling it next cycle; `/api/feeds` lists it; and the
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
