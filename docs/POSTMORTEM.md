# FinScrape - Postmortem Template

A postmortem is written after a real incident, once that incident is closed, and within 5 working days of the close. It is a record of what the system did, what the process missed, and what changes next, not a story about who was on call.

This file is the template. Written postmortems live in `docs/postmortems/`, one file per incident, named `YYYY-MM-DD-<slug>.md`. The only file in that directory today is a clearly labelled exercise, kept so the shape of a write-up is visible before the first real one exists.

As of 2026-11-26 `notes.md` records no real incident, so no real postmortem exists yet. Nothing in this repository should be read as an incident record until a file in `docs/postmortems/` says so in its own words.

## How to use this template

- Copy this template to `docs/postmortems/YYYY-MM-DD-<slug>.md`, using the incident's close date and a short slug such as `llm-provider-outage`.
- Keep numbers measured, not remembered: paste the command output into the Evidence links section rather than retyping a figure from memory.
- Link the finished postmortem from the milestone or plan row when it is done, so the work item and the write-up point at each other.
- Write it for the next person who hits the same failure. No blame: name systems, signals and decisions, never people.

## Summary

Two or three sentences: what broke, the window in UTC from first bad state to resolution, and the one number that shows the size.

- Window (UTC): `<start>` to `<end>`, `<duration>`
- Headline number: `<events missed | hours stale | requests failed | users affected>`

## Impact

Numbers only. State events missed, hours of staleness, requests failed, users affected, and the SLO budget spent, naming which SLO in [SLO.md](SLO.md) and saying how it was measured.

| Measure | Value | Source |
|---|---|---|
| Events missed or degraded | `<n>` | `<query or log>` |
| Hours of staleness | `<n>` | `<check_prod output>` |
| Requests failed | `<n>` of `<n>` | `<dashboard or log>` |
| Users affected | `<n>` | `<session or request count>` |
| SLO touched | SLO `<n>` `<name>` | [SLO.md](SLO.md) |
| Budget spent | `<n>`% of the monthly budget | `<measurement>` |

## Timeline

One UTC row per fact, detection through mitigation to resolution, with the command or dashboard that shows it. Write `unknown` rather than guessing a timestamp.

| Time (UTC) | Phase | Event | Command or dashboard |
|---|---|---|---|
| `<YYYY-MM-DD HH:MM>` | first bad state | `<what changed>` | `<signal>` |
| `<YYYY-MM-DD HH:MM>` | detected | `<what fired>` | `<command>` |
| `<YYYY-MM-DD HH:MM>` | acknowledged | `<who saw it, where>` | `<channel>` |
| `<YYYY-MM-DD HH:MM>` | mitigated | `<what stopped the bleeding>` | `<command>` |
| `<YYYY-MM-DD HH:MM>` | resolved | `<what restored normal>` | `<command>` |

## Detection

Which signal fired, or why nothing did, and the time from first bad state to detection. Name the real route, metric or log line from [INCIDENTS.md](INCIDENTS.md), for example `GET /api/health` reporting `heuristic_alert`, the `worldfin_source_age_seconds` series, or `gh run view --log`.

- Signal: `<route, metric or log line>`
- Time to detect: `<n>` minutes
- Found by: `<monitor | manual build | user report>`

## Root cause

One sentence naming the mechanism, then the sequence that made it bite. Separate the upstream cause from any local fault; write `no local fault established` when that is the finding.

- Upstream cause: `<what failed outside the repo>`
- Local fault: `<what this repo did or failed to do, or "no local fault established">`
- Mechanism: `<one sentence>`

## Contributing factors

What made the failure possible, likely, or slow to see. Systems and process only, including whatever made detection slow.

- `<factor>`
- `<factor>`
- `<what delayed detection>`

## What went well

What actually helped, each with the artifact that proves it.

- `<what helped>`: `<log line, run URL or query result>`
- `<what helped>`: `<artifact>`

## What went wrong

What did not help, with the same standard of evidence. This is about signals and tooling, not people.

- `<what did not help>`: `<artifact>`
- `<what was missing>`: `<artifact or absence>`

## Action items

The owner is the repo owner, a single operator, so every action below names the repo owner and a real due date. `TBD` is not a date and is not accepted; if the date is genuinely unknown, the action is to pick one.

| Action | Owner | Due date | Tracking link |
|---|---|---|---|
| `<specific change>` | repo owner | `<YYYY-MM-DD>` | `<milestone row or issue>` |
| `<specific change>` | repo owner | `<YYYY-MM-DD>` | `<milestone row or issue>` |
| `<specific change>` | repo owner | `<YYYY-MM-DD>` | `<milestone row or issue>` |

## Evidence links

The artifacts a reader can open to check the claims above: the GitHub Actions run, the correlation id or `X-Request-ID`, the `source_health` row, the `python -m scripts.check_prod.py` output, and the Render deploy id.

- GH run: `<https://github.com/.../actions/runs/...>`
- Correlation id / `X-Request-ID`: `<value>`
- `source_health` row: `<source, status, fetched_at>`
- `check_prod` output: `<pasted line>`
- Render deploy id: `<dep-...>`

## Related

- [SLO.md](SLO.md)
- [INCIDENTS.md](INCIDENTS.md)
- [RUNBOOK.md](RUNBOOK.md)
- [../docs/postmortems/2026-11-26-exercise.md](postmortems/2026-11-26-exercise.md)
