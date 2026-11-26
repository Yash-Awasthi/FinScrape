# Findings, ranked, and what was fixed

Source: `docs/ui/AUDIT.md` (eight findings, measured at 654a3ef). This is the ordered
worklist the plan asks for: rank by user impact, fix in that order, re-measure. Every
number below was produced by `docs/ui/audit.cjs`; the after run is
`docs/ui/after/audit-after.txt`.

Scale used for the ranking: **blocks use** > **misleads** > **slows** > **polish**.
Within one rank, the finding with more affected surfaces goes first.

## Ranking and outcome

| # | Finding | Impact | Touches | Outcome |
| --- | --- | --- | --- | --- |
| 1 | Scenario detail renders in the 300 px rail at >=1100 px (`.ev-host { display:block }` beats `hidden`) | blocks use | styles.css | fixed |
| 2 | Four token pairs under 4.5:1 (`--down` on panel 4.44, `--chart-1` 3.48, `#fff` on accent 3.68, accent on accent-soft 4.05) | misleads, blocks low-vision use | tokens.css | fixed before this row at `701c041`, re-verified here |
| 3 | 124 of 210 controls under 44 px at 360; 61 under WCAG 2.2's 24 px | blocks use with a thumb | styles.css | partial: feed and chrome controls now 44 px at <=700, 34 remain under 24 |
| 4 | Market tape silently hides 9 of 11 tiles at 360 and 4 at 1440 | misleads (a clipped tile reads as missing) | styles.css | fixed at 1440 (1016/1016); at 360 the tape scrolls inside its panel |
| 5 | Spacing had no rhythm: 143 hard-coded px values, 100% off the 4/8/12/16/24/32/48 scale | polish, slows scanning | styles.css, landing.css | fixed: 0 hard-coded px left |
| 6 | 88 hard-coded font sizes, 100% off the 12/14/16/20/24/32 scale, five under 12 px | slows, blocks low-vision | styles.css, landing.css | fixed: 0 hard-coded px, floor is now 12 px |
| 7 | Refresh control reported as a fixed FAB overlapping content at 360 | blocks use | styles.css | not reproduced after the header rework; no fixed refresh exists any more |
| 8 | `audit.cjs` crashed at the landing palette section, hiding landing contrast | slows (measurement) | docs/ui | fixed: the section now guards a missing token and prints a statement |

## Three candidates per finding, scored

Score is `impact (1-3) - effort (1-3)`, so the highest score is the cheapest real fix.

| # | A | B | C | Chosen |
| --- | --- | --- | --- | --- |
| 1 | `[hidden]{display:none!important}` globally (2/1, +1) | `.ev-host[hidden]{display:none}` (3/1, +2) | move the hosts out of the grid (3/2, +1) | B |
| 2 | raise the four tokens (3/1, +2) | drop the colours and use text only (2/2, 0) | per-surface overrides (1/3, -2) | A, at `701c041` |
| 3 | 44 px minimum on every control everywhere (3/3, 0) | 44 px on phone-width controls only, 24 px floor elsewhere (3/2, +1) | keep 24 px and rely on spacing (1/1, 0) | B |
| 4 | let tiles shrink so all 11 fit (2/1, +1) | horizontal scroll on the tape (2/1, +1) | two-row grid (2/2, 0) | A at >=700, B under it |
| 5 | snap every spacing value to the scale in one pass (1/1, 0) | tokenise only exact matches, leave the rest (1/1, 0) | hand-tune each component (1/3, -2) | A |
| 6 | snap every size to the scale in one pass (2/1, +1) | tokenise exact matches only (2/2, 0) | leave the sub-12 px sizes (0/1, -1) | A |
| 7 | verify and drop the finding (1/1, 0) | add a defensive position rule (1/2, -1) | — | A |
| 8 | guard the missing token and keep measuring (2/1, +1) | delete the landing section (1/1, 0) | — | A |

## Fixes in this row, in rank order

1. `.ev-host[hidden] { display: none }` next to the `.ev-host` rule, so the hidden
   detail host stops holding the first grid cell.
2. Contrast is re-verified against the committed palette; all 29 measured pairs pass,
   including the filled control (`#fff` on `--accent-bg` 5.17:1).
3. `@media (max-width: 700px)`: tabs, refresh, filter chips, day buttons, scenario chips,
   story toggles, follow buttons and the inspector close control get `min-height: 44px`.
4. `.mkt-tile` becomes `flex: 1 1 84px; min-width: 84px` (132 px on phones), so the tape
   fits its panel at desktop widths and scrolls as a unit on a phone. The page itself
   still never scrolls sideways (`scrollWidth == innerWidth` on all nine surfaces).
5. Every `padding`/`margin`/`gap`/`inset`/offset px value snapped to the space scale and
   written as `var(--space-N)`; negatives become `calc(-1 * var(--space-N))`.
6. Every `font-size` px value snapped to the type scale and written as `var(--font-*)`;
   the smallest step is 12 px, so nothing renders at 9-11 px any more.
7. No code: the fixed refresh no longer exists, so there is nothing to move.
8. `docs/ui/audit.cjs`: the landing palette section reports a missing token instead of
   throwing, reads `--accent-bg` for the filled control with a fallback, and accepts
   `AUDIT_COMMIT=WORKTREE` for a before/after run on files as authored.

## Before and after

| Measure | Before (654a3ef) | After |
| --- | --- | --- |
| Hard-coded spacing px | 304 declarations, 35 values, 188 off-scale (61.8%) | 0 declarations |
| Hard-coded font-size px | 124 declarations, 19 sizes, 87 off-scale (70.2%), 5 under 12 px | 0 declarations |
| Distinct hex colours | 75 uses, 50 distinct, 31 outside tokens.css | unchanged (palette work landed at `701c041`) |
| Contrast pairs under 4.5:1 | 6 | 0 of 29 |
| Controls under 24 px at 360 | 61 of 210 | 34 of 276 |
| Controls under 44 px at 360 | 124 of 210 | 187 of 276 (more controls exist now; the dense table links are exempt at 24 px) |
| Market tape, 1440 | 1016 px visible of 1444 px content | 1016 of 1016, all 11 tiles |
| Market tape, 360 | 288 px visible of 1444 px | 292 visible, 1532 content, scrolls inside the panel |
| Page-level horizontal scroll | none | none |

## Deferred

- Two-tone links and inline sentence links keep 24 px heights: WCAG 2.5.8 exempts inline
  text, and padding them to 44 px would wreck the tables. Reported, not hidden.
- The landing hero's large `clamp()` steps are deliberately off-scale (display type) and
  are not part of the 12-32 px UI scale.
