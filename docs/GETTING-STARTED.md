# Getting started with the API

The API listens on <http://localhost:8010> after `make demo`; Swagger is at
<http://localhost:8010/docs> and the generated getting-started page, with one curl for
every endpoint, is at <http://localhost:8010/docs/getting-started>. That page is built
from the live schema on each request, so it is always current. This file is the short
human version: the demo, the base URL, auth, one request per group, and the Postman
collection.

## Run the demo and probe it

```bash
make demo
curl -s localhost:8010/health
```

`make demo` brings up Postgres and the API, then loads the seeded dataset. `/health`
answers `{"status":"ok","db":true,...}`; `/ready` answers 200 only while the database
responds. The walkthrough from a fresh clone is [ONBOARDING.md](ONBOARDING.md).

## Auth

Reads are open. Every mutating route takes the API key in `X-API-Key` (or as
`Authorization: Bearer <key>`), and answers 401 without it. The key comes from
`FINSCRAPE_API_KEY`; when that is unset the published development value `local-dev-key`
from `.env.example` is accepted, which is why the commands below use
`${FINSCRAPE_API_KEY:-local-dev-key}`. Set a real key before exposing the API beyond your
machine; [SECURITY.md](SECURITY.md) has the reasoning. Telegram's webhook is the one
write route with its own secret header instead.

## One request per group

Health and readiness:

```bash
curl -s localhost:8010/health
curl -s localhost:8010/ready
curl -s localhost:8010/api/health
```

Events and the numbers the dashboard polls:

```bash
curl -s 'localhost:8010/api/events?limit=5'
curl -s localhost:8010/api/events/1
curl -s localhost:8010/api/stats
curl -s localhost:8010/api/dates
```

Ingest is the one write on this group; it needs the key:

```bash
curl -s -X POST localhost:8010/api/events \
  -H "X-API-Key: ${FINSCRAPE_API_KEY:-local-dev-key}" \
  -H 'Content-Type: application/json' \
  --data '{"events": [{"subject": "Demo Corp beats estimates", "event_type": "earnings", "verdict": "INVEST"}]}'
```

Analysis and scenarios (the AI routes need a configured model; without one they fall
back to the heuristic):

```bash
curl -s 'localhost:8010/api/ai/analyze?id=1'
curl -s 'localhost:8010/api/scenarios?limit=3'
curl -s 'localhost:8010/api/scenarios/1'
curl -s 'localhost:8010/api/storylines?limit=5'
```

Market data:

```bash
curl -s 'localhost:8010/api/market/quotes?symbols=AAPL'
curl -s 'localhost:8010/api/candles?symbol=AAPL&period=1mo&interval=1d'
```

Track record and scoring:

```bash
curl -s localhost:8010/api/accuracy
curl -s localhost:8010/api/accuracy/by-variant
curl -s 'localhost:8010/api/outcomes?limit=5'
curl -s localhost:8010/api/reliability
curl -s 'localhost:8010/api/predict/1'
```

Sources and discovery:

```bash
curl -s localhost:8010/api/feeds
curl -s 'localhost:8010/api/correlations?limit=5'
curl -s 'localhost:8010/api/suggestions?limit=5'
curl -s localhost:8010/api/sectors
```

Alert rules; the writes need the key:

```bash
curl -s localhost:8010/api/alerts/rules
curl -s -X POST localhost:8010/api/alerts/rules \
  -H "X-API-Key: ${FINSCRAPE_API_KEY:-local-dev-key}" \
  -H 'Content-Type: application/json' \
  --data '{"name": "High-signal earnings", "conditions": [{"field": "event_type", "operator": "eq", "value": "earnings"}, {"field": "signal_score", "operator": "gte", "value": 70}]}'
curl -s -X PATCH localhost:8010/api/alerts/rules/RULE_ID \
  -H "X-API-Key: ${FINSCRAPE_API_KEY:-local-dev-key}" \
  -H 'Content-Type: application/json' \
  --data '{"enabled": false}'
```

Watchlists use `X-Watchlist-Owner` as a label (default `default`) and the key for writes:

```bash
curl -s localhost:8010/api/watchlists
curl -s -X POST localhost:8010/api/watchlists \
  -H "X-API-Key: ${FINSCRAPE_API_KEY:-local-dev-key}" \
  -H 'Content-Type: application/json' \
  --data '{"name": "Energy", "items": [{"kind": "sector", "value": "energy"}]}'
curl -s localhost:8010/api/watchlists/1/feed
```

The full list, with every query parameter each route documents, is on
<http://localhost:8010/docs/getting-started> and in Swagger.

## Import the Postman collection

`docs/postman.json` is a Postman v2.1 collection generated from the same schema: one
request per path and method, a folder per path prefix, a JSON body built from the request
schema and the `X-API-Key` header wherever the route needs it.

1. Postman: **Import** -> **Files** -> `docs/postman.json`.
2. Set the `baseUrl` variable to `http://localhost:8010` (the default) if you point it at
   another host.
3. Set `apiKey` to your key; the default is the published development value. Requests
   that do not need a key do not send the header.
4. Optional query parameters are imported disabled; enable the ones you want.

## Regenerate it

The collection is committed, not hand-edited:

```bash
python -m scripts.postman --write docs/postman.json
make postman-check
```

`--write` rewrites the file from `create_app().openapi()`; `make postman-check` fails when
the committed file and the contract disagree, and it runs in `make ci` and `make verify`
next to `openapi-check`. Generating twice produces byte-identical output: ids are derived
from the method and path, and nothing is timestamped. The getting-started page needs no
regeneration; it is rendered from the schema per request.
