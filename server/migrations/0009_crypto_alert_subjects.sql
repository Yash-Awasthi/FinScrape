-- CoinGecko alerts were titled "{name} ({SYM}) {verb} {pct:+.1f}% in 24h" and an old
-- normalizer kept only lowercase words, so the last digit left is the decimal.
UPDATE events e
SET subject = initcap(m[1]) || ' (' || upper(m[2]) || ') ' || m[3] || ' '
    || CASE m[3] WHEN 'surged' THEN '+' ELSE '-' END
    || left(m[4], -1) || '.' || right(m[4], 1) || '% in 24h'
FROM (
    SELECT id, regexp_match(subject, '^([a-z0-9 ]+) ([a-z0-9]+) (surged|dropped) ([0-9]{2,}) in 24h$') AS m
    FROM events
    WHERE sources ? 'coingecko'
) s
WHERE e.id = s.id AND s.m IS NOT NULL;
