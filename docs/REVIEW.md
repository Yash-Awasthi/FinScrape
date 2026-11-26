# Quarterly review

One review per quarter: dependencies, licences, and model quality. The generated block
below is checked by CI, so a quarter cannot pass silently.

## What it covers

1. **Dependencies.** Upgrade the lock file with `uv lock --upgrade` (the weekly Dependabot
   PRs land the same changes), then read `make audit` for known vulnerabilities and
   `make sbom` for the resolved component list. Allowlist entries in
   `security-audit-allowlist.json` must still be unexpired.
2. **Licences.** Every package in `uv.lock` is looked up in the installed environment and
   its licence recorded. An unlisted licence or a copyleft term (GPL, AGPL, LGPL, MPL,
   EPL, CDDL, SSPL) is a decision, not a fact: keep it with a reason or replace it.
3. **Model quality.** The newest row per model in [EVAL.md](EVAL.md) is compared against
   the 5-point rule there: a run more than 5 points below the stored baseline for the same
   model and prompt is refused. A configured model with no stored row is a gap, not a
   pass.

## Cadence

First week of January, April, July and October. There is no repository schedule: GitHub
disables them after 60 quiet days, so the Cloudflare cron Worker is the only scheduler in
this project. The check rides on every CI run instead (`docs/REVIEW.md` block plus the
review date): once 100 days pass without a review, every run fails until the block is
regenerated and committed. The failure is the reminder.

## Who decides

The repository owner (`@Yash-Awasthi`, see `.github/CODEOWNERS`). The generated block
records what was measured; the decision and its reason go in the "Last four reviews" table.

## Inputs

Run these before regenerating the block:

```bash
make audit        # known vulnerabilities, allowlist expiry
make sbom         # dist/sbom.cdx.json from uv.lock
make facts-check  # docs still quote counts the tree produces
make eval-gate    # 5-point model gate against the stored baseline
```

Dependency upgrades arrive as Dependabot pull requests; `uv lock --upgrade` is the local
equivalent when a bump has to be driven by hand. Framework and provider context is in
[COST.md](COST.md) and [DEPLOY.md](DEPLOY.md).

## Decision rules

- **Unlisted licence, or a copyleft term.** Record `keep` or `replace` in the review table,
  with the reason. Silence is not a decision.
- **Model more than 5 points worse.** Replace the model, or re-record the baseline if the
  change was intended. A worse number without a decision blocks the next deploy.
- **Overdue review or stale block.** CI fails. The failing job is the reminder: run
  `--write`, then commit `docs/REVIEW.md`.

## Current review

The block is a snapshot: the licence tally comes from the environment of the machine
that ran the review, so CI compares only the rows the repository itself derives (locked
packages, eval rows) and enforces the review date.

<!-- review:start -->
Reviewed: 2026-11-26

| Measure | Value |
|---|---|
| Locked packages | 147 |
| Licence families | MIT 54, not-installed 37, BSD 30, Apache-2.0 16, MPL 3, PSF 2, custom-text 2, ISC 1, LGPL 1, unknown 1 |
| Packages needing review | certifi (MPL-2.0)<br>orjson (MPL-2.0 AND (Apache-2.0 OR MIT))<br>peewee (unknown)<br>tld (MPL-1.1 OR GPL-2.0-only OR LGPL-2.1-or-later)<br>tqdm (MPL-2.0 AND MIT) |
| Newest eval row per model | keyword-baseline: 63.8% sector, 100.0% JSON, 2026-11-24 |
| Configured models with no eval row | qwen3.8-flash:free, mimo-v2.6-flash:free, deepseek-v4.1-flash:free |
<!-- review:end -->

## Decisions from the 2026-11-26 review

- `certifi`, `orjson`, `tqdm` (MPL-2.0, file-level copyleft): **keep**. They are
  unmodified dependencies; MPL-2.0 requires no more than keeping their licence text.
- `tld` (MPL-1.1 OR GPL-2.0-only OR LGPL-2.1-or-later): **keep** under MPL-1.1, the
  option the project selected; the GPL alternatives are not taken.
- `peewee` (licence metadata missing, MIT upstream): **keep**, and the package stays
  flagged until its metadata reports a licence.
- `qwen3.8-flash:free`, `mimo-v2.6-flash:free`, `deepseek-v4.1-flash:free`: **no stored
  eval row**. The first is not selected today; the other two need a recorded run
  (`make eval-live MODEL=...`) before the next model switch, per `docs/DEPLOY.md`.

## Last four reviews

| Date | Outcome |
|---|---|
| 2026-11-26 | Baseline: 147 locked packages; 5 copyleft or unlisted licences kept with reasons above; 3 configured models still have no stored EVAL row (owner action). |
