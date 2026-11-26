# Key rotation without downtime

Rotating `FINSCRAPE_API_KEY` or the Telegram webhook secret used to mean a window where
the caller held the new value and the API still expected the old one. Both now accept a
**current** and a **previous** value, so the order is always add-then-remove:

1. Put the new value in the current variable and the old one in `*_PREVIOUS`.
2. Deploy/restart once. Both values are valid.
3. Move every caller to the new value.
4. Clear `*_PREVIOUS` and deploy again. The old value stops working.

`FINSCRAPE_API_KEY_PREVIOUS` and `TELEGRAM_WEBHOOK_SECRET_PREVIOUS` are the two overlap
variables. They are read through `server/settings.py`; comparison is constant-time for
every configured value (`server/auth.py`, `server/routes/telegram.py`).

## API key

Variables: `FINSCRAPE_API_KEY` (current), `FINSCRAPE_API_KEY_PREVIOUS` (old, overlap only).

```bash
NEW=$(openssl rand -hex 32)
# Render dashboard / GitHub secrets / .env: set both, then deploy or recreate api+worker
# FINSCRAPE_API_KEY=$NEW
# FINSCRAPE_API_KEY_PREVIOUS=<old>
```

Verify both keys pass authentication without writing a row. An empty JSON body reaches
the route and fails validation with **422**; a bad key never reaches it and returns
**401**, so `422` is the proof that the key was accepted:

```bash
for KEY in "$NEW" "$OLD"; do
  curl -s -o /dev/null -w '%{http_code}\n' \
    -X POST "$API_URL/api/events" \
    -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d '{}'
done
# expected during the overlap:
# 422
# 422
```

Move callers (cron Worker `GH_TOKEN` is separate; alert scripts, notebooks, the dashboard
write path) to `$NEW`. Then clear the previous value and deploy:

```bash
# FINSCRAPE_API_KEY=$NEW
# FINSCRAPE_API_KEY_PREVIOUS=   (unset or empty)
```

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$API_URL/api/events" \
  -H "X-API-Key: $OLD" -H 'Content-Type: application/json' -d '{}'
# expected: 401
```

Expected end state: new key -> 422, old key -> 401, and no caller logs a 401.

## Telegram webhook secret

Variables: `TELEGRAM_WEBHOOK_SECRET` (current), `TELEGRAM_WEBHOOK_SECRET_PREVIOUS` (old).

```bash
NEW=$(openssl rand -hex 32)
# set TELEGRAM_WEBHOOK_SECRET=$NEW and TELEGRAM_WEBHOOK_SECRET_PREVIOUS=<old>, deploy
curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  --data-urlencode "url=$API_URL/api/telegram/webhook" \
  --data-urlencode "secret_token=$NEW"
curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo"
```

Expected: `{"ok":true,...}` from `setWebhook`; `getWebhookInfo` shows the URL and no
`last_error_message`. During the overlap the API accepts either secret, so updates already
in flight with the old header are not dropped. After Telegram reports the new secret and a
test command round-trips, clear the previous variable and redeploy. A request with the old
secret now gets the usual silent `200 {"ok": true}` and is not acted on.

## Rollback

The old value is still valid until step 4, so rollback is a settings change, not a restore:

- If the new API key is wrong or not deployed everywhere, set `FINSCRAPE_API_KEY` back to
  the old value, leave `*_PREVIOUS` empty, and redeploy. Callers that already moved keep
  working only if the old value is their current one; otherwise re-run this procedure with
  the values swapped.
- If `setWebhook` fails, do not clear `TELEGRAM_WEBHOOK_SECRET_PREVIOUS`; the bot keeps
  receiving with the old secret. Re-run `setWebhook` and check the token.
- Never delete the previous value in the same deploy that introduces the new one. That is
  the only sequence that creates a 401 window.

## Other keys

- LLM provider keys rotate as a queue: `OPENAI_API_KEYS` takes a comma-separated list, a
  429 moves that key to the back, and the next key answers
  (`tests/test_key_rotation.py`). Adding a key needs no restart of the queue's state.
- The database password is not covered by the overlap variables. Use
  `ALTER USER ... PASSWORD` with both old and new auth configured at the server, then
  update `WORLDFIN_DATABASE_URL` and restart; see `docs/RUNBOOK.md` section 5.

## Verify

```bash
uv run -p 3.14 --group server --group dev pytest \
  tests/server/test_secret_rotation.py tests/test_key_rotation.py \
  tests/server/test_phase13.py -q
```

Expected: all pass. The overlap test asserts both values pass authentication and the
cleared previous value is rejected.

Escalate to the owner if either check returns 401 for the **current** value after a
deploy: that is a configuration error, not a rotation step, and the previous value should
stay configured until it is fixed.
