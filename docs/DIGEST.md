# Weekly digest template

The weekly digest is a stored template for one honest summary of the track
record served by `/api/accuracy`. `server/alerts_digest.py` fills the sections
below, in this order, from that track record and writes `digest-<ISO week>.md`
plus a matching PDF into a local directory when the CLI runs:

```
python -m server.alerts_digest --fixture <track record.json> --out <dir>
```

Email delivery is not implemented: the sender and domain are owner-blocked, so
nothing is sent. The CLI writes files locally and prints their paths.

## Window

The from/to dates of the scored calls, taken from the `window` object of the
`/api/accuracy` response; "not recorded" when it is absent.

## Calls scored

The total number of calls and how many of them were scored, so the rate below
has a denominator the reader can see.

## Hit rate

The hit rate as a percentage with `n=<scored>` and the Wilson 95% interval from
the `ci95` field of `/api/accuracy`; "interval not recorded" when it is absent.

## By verdict

A table of verdict, hits, n and hit rate from the `by_verdict` breakdown of
`/api/accuracy`.

## Best call

The strongest scored call from the `best` entry (subject, verdict, move, date),
or "not recorded" when the track record has none.

## Worst call

The weakest scored call from the `worst` entry, or "not recorded" when the
track record has none.

## Disclaimer

A fixed sentence: research and education only, not financial advice, and past
performance is not indicative of future results.
