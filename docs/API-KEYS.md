# Per-consumer API keys (plan m4.4)

The API is read-only by design, but a consumer (a partner page, a notebook, the embed
widget) still needs its own identity and a ceiling. Two things exist here: the operator
key (`FINSCRAPE_API_KEY`, one per deployment, guards every mutating route) and consumer
keys (one per caller, tiered and rate-limited).

## Tiers

| Tier    | Calls per rolling minute | Use |
|---------|--------------------------|-----|
| `read`  | 60                       | public reads: events, scenarios, accuracy |
| `write` | 120                      | read plus routes that change state |

A `read` key on a write-tier dependency answers `403`. Over the ceiling, the response is
`429` with a `Retry-After` header in seconds; the window is a per-key sliding minute held
in memory, so a multi-process deployment multiplies it (one process per key is the
assumption, same as `WORLDFIN_RATE_LIMIT_PER_MIN`).

## Storage

The plaintext key (`wfk_` plus 32 random bytes, urlsafe) is returned **once**, by the
issue call. Only `sha256(raw)` hex is stored in `consumer_keys.key_hash`; the first 12
characters are kept as `key_prefix` so an operator can tell keys apart in the list. A
dump of the table cannot be replayed.

## Issue, list, revoke

```bash
# issue (the response is the only place the key appears)
curl -sS -X POST "$FINSCRAPE_API_URL/api/admin/keys" \
  -H "X-API-Key: $FINSCRAPE_API_KEY" \
  -H "Content-Type: application/json" \
  --data '{"label": "partner-dashboard", "tier": "read"}'

# list (never returns a hash or the key)
curl -sS "$FINSCRAPE_API_URL/api/admin/keys" -H "X-API-Key: $FINSCRAPE_API_KEY"

# revoke (idempotent; sets revoked_at once)
curl -sS -X DELETE "$FINSCRAPE_API_URL/api/admin/keys/<id>" \
  -H "X-API-Key: $FINSCRAPE_API_KEY"
```

A revoked or unknown key answers `401`; revocation never deletes the row, so the audit
trail (creation time, last use) survives.

## Rotation

1. Issue a second key for the consumer with the same tier.
2. Deploy the consumer with the new key.
3. Watch `last_used_at` on the old key go quiet.
4. Revoke the old key.

Keeping both live during the switch is safe: each key has its own rate-limit window and
its own id in the list.

## Using a key

Send it in `X-API-Key` (or `Authorization: Bearer <key>`). The dependency is exported as
`server.routes.keys.require_consumer("read" | "write")`, so a route opts in with
`dependencies=[Depends(require_consumer("read"))]`.
