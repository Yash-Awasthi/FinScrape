# UI audit — the "before" baseline

Measurements of the dashboard as committed in `654a3ef`, taken by `docs/ui/audit.cjs`.
The script reads CSS with `git show 654a3ef:<path>`, so it reports the baseline even when
the worktree has other uncommitted edits. Tap targets and horizontal overflow are measured
in Chromium (Playwright) against a build of the same commit, at 360 and 1440 px, with the
fixtures in `docs/ui/serve.cjs`; the PNGs in `docs/ui/before/` are used only to confirm
what the numbers describe.

Reproduce:

```sh
node docs/ui/audit.cjs                    # spacing, type, colour, contrast, breakpoints
git archive 654a3ef web | tar -x -C /tmp/base
mklink /J \tmp\base\web\node_modules <repo>\web\node_modules   # or copy it
cd /tmp/base/web && npm run build
node docs/ui/audit.cjs --dist=/tmp/base/web/dist               # + tap targets, overflow
```

All numbers below are printed by that script; two consecutive runs were byte-identical.

## Spacing

Scope: `padding|margin|gap|inset|top|right|bottom|left` in `web/src/styles.css` and
`web/src/landing/landing.css`.

| Metric | Value |
| --- | --- |
| px values in declarations | 304 |
| distinct values | 35 |
| outside {4,8,12,16,24,32,48} | 188 (61.8%) |
| rhythm only (padding/margin/gap) outside the scale | 183 of 299 (61.2%) |
| most used off-scale values | 6px×42, 10px×22, 2px×18, 14px×13, 3px×13, 9px×13 |
| scale steps never used as raw px | 32px, 48px |
| `var(--space-*)` uses | 0 |
| distinct `border-radius` values | 15 |

## Type

| Metric | Value |
| --- | --- |
| `font-size` declarations (resolved to px) | 124 |
| distinct sizes | 19 |
| outside {12,14,16,20,24,32} | 87 (70.2%) |
| off-scale by frequency | 11px×25, 13px×18, 11.5px×13, 12.5px×9, 13.5px×4, 26px×3 |
| sizes below 12px | 9.5, 10, 10.5, 11, 11.5 (45 declarations) |
| `font-family` declarations | 23 (22 `var(--mono)`, 1 `"Inter", system-ui`) |
| `font-weight` declarations | 40 (600×15, 800×14, 700×9, 500×1, 400×1) |
| `var(--font-*)` uses | 0 |

## Colour

| Metric | Value |
| --- | --- |
| hex literals in the 6 CSS files | 75 uses, 50 distinct |
| distinct hex outside `tokens.css` | 31 |
| `rgb()` / `rgba()` / `hsl()` calls | 26 |
| per file | tokens 21, landing 19, styles 12, mobile/motion/freshness 0 |
| `var(--<colour>)` uses | 222 |

## Tap targets (live, 360 and 1440, all 9 surfaces)

| Viewport | Interactive elements | Under 44 in w or h | Also under 24 (WCAG 2.5.8) |
| --- | --- | --- | --- |
| 360px | 210 | 124 | 61 |
| 1440px | 278 | 197 | 100 |

Failures, as rendered (distinct selectors; w–h is the measured box):

| Selector | 360px | 1440px |
| --- | --- | --- |
| `button.follow` (feed, sectors) | 20–42 × 18 | 20–42 × 18 |
| `button.inspector-close` | 21 × 19 | 21 × 19 |
| `button.ffilter` / `.topic` / `.active` | 43–80 × 25 | 43–80 × 25 |
| `button.day` (calendar) | 98–105 × 25 | 98–105 × 25 |
| `button.sc-tk` (scenario chips) | 38–50 × 22 | 38–50 × 22 |
| `button.story-toggle` | 85 × 20 | 85 × 20 |
| `span.followed` / `span.held` (desk chips) | 81–118 × 20 | 81–118 × 20 |
| desk key/position `input`, `button` | 73 × 18, 40 × 22 | 73–180 × 18, 40 × 22 |
| `button.ai-btn`, `.ai-btn.secondary` | 112–156 × 33 | 112–156 × 33 |
| `input.candles-symbol`, `select.candles-period`, Load | 154 × 32, 66 × 32, 56 × 32 | 522 × 32, 66 × 32, 56 × 32 |
| `button.sector-chip` | 116–167 × 33 | 116–167 × 33 |
| `li.src-row` | 288 × 34 | 656 × 34 |
| `li` (calls list, `.call-list li`) | 288 × 67 | 656 × 32 |
| `button.refresh` | 48 × 48 (pass) | 33 × 28 |
| `a.ev-back`, `a.ev-link`, feed subject links | 129 × 17, 76–218 × 17, 270–292 × 35 | 129 × 17, 76–247 × 17, 306–392 × 17 |

Passes worth noting: `.tabs a` 69 × 44 at 360 (bottom nav), 60 × 50 at 1440; `.mkt-tile`
124 × 106; `a.btn` 166 × 43 (1 px under); `.sug-row`, `.grid-table` rows and `tr[data-event-id]`
all exceed 44 in both dimensions.

## Contrast (WCAG 2.1, sRGB relative luminance)

| Pair | Hex | Ratio | 4.5 body | 3.0 UI |
| --- | --- | --- | --- | --- |
| text on bg | #d8dce4 / #0b0e14 | 14.05 | pass | pass |
| text on panel | #d8dce4 / #121621 | 13.14 | pass | pass |
| text on panel-2 | #d8dce4 / #0f131b | 13.53 | pass | pass |
| muted on bg | #8a909b / #0b0e14 | 6.02 | pass | pass |
| muted on panel | #8a909b / #121621 | 5.63 | pass | pass |
| muted on panel-2 | #8a909b / #0f131b | 5.79 | pass | pass |
| up on bg / panel / panel-2 | #16c784 | 8.77 / 8.20 / 8.44 | pass | pass |
| down on bg | #ea3943 / #0b0e14 | 4.75 | pass | pass |
| down on panel | #ea3943 / #121621 | 4.44 | **FAIL** | pass |
| down on panel-2 | #ea3943 / #0f131b | 4.57 | pass | pass |
| accent on bg / panel / panel-2 | #3b82f6 | 5.25 / 4.91 / 5.06 | pass | pass |
| warn on bg / panel / panel-2 | #f5a623 | 9.53 / 8.91 / 9.18 | pass | pass |
| chart-1 on panel | #0072b2 / #121621 | 3.48 | FAIL | pass |
| chart-2 on panel | #e69f00 / #121621 | 8.02 | pass | pass |
| chart-3 on panel | #009e73 / #121621 | 5.28 | pass | pass |
| chart-4 on panel | #cc79a7 / #121621 | 5.90 | pass | pass |
| chart-5 on panel | #56b4e9 / #121621 | 7.83 | pass | pass |
| chart-6 on panel | #d55e00 / #121621 | 4.67 | pass | pass |
| chart-7 on panel | #f0e442 / #121621 | 13.66 | pass | pass |
| #fff on accent (`.ffilter.active`) | #ffffff / #3b82f6 | 3.68 | **FAIL** | pass |
| muted on panel-head | #8a909b / #171c29 | 5.30 | pass | pass |
| accent on accent-soft (`.chain-badge`) | #3b82f6 / #1b2740 | 4.05 | **FAIL** | pass |
| landing text on bg | #e8eef6 / #0a0d12 | 16.67 | pass | pass |
| landing muted on bg | #8a98ab / #0a0d12 | 6.63 | pass | pass |
| landing muted2 on bg | #5e6b7d / #0a0d12 | 3.59 | **FAIL** | pass |
| landing muted2 on card | #5e6b7d / #131820 | 3.29 | **FAIL** | pass |

## Breakpoints and horizontal overflow

| Query | Where | Effect |
| --- | --- | --- |
| max-width: 1100px | styles.css:1436 | `.app-main` to one column, `.panel-grid` to 6 columns, panels span 6 or 3 |
| max-width: 700px | styles.css:1459, mobile.css:3, freshness.css:15 | header wraps, panel grid becomes a flex column, KPIs to one column |
| max-width: 900px | landing.css:664 | hero to one column, nav links hidden, 2-up grids, float cards hidden |
| max-width: 560px | landing.css:697 | landing grids to one column |
| prefers-reduced-motion | styles.css:1720, landing.css:642 | transitions and marquee off |

- `.app-grid` has no rule in any media query; the collapse is on `.app-main`. Bottom nav:
  yes, `.head-left .tabs` becomes `position: fixed` at ≤700 (mobile.css:14–39) with
  `min-height: 44px` per tab.
- Tables never scroll sideways: no `overflow-x: auto` on `.grid-table` or `.feed`. The only
  two `overflow-x: auto` rules are `.tabs` (styles.css:151) and `.mkt-tape` (styles.css:1388).
  At ≤700 tables get `table-layout: fixed` and `white-space: normal` (mobile.css:60–81).
- Page level: `document.scrollWidth == innerWidth` on all 9 surfaces at both widths (over=0).
  Nothing is clipped off the page.
- Inside the page, the market tape does overflow: 11 tiles, 124 px each. At 360 the pane is
  288 px against 1444 px of content (about 2.3 tiles visible, 9 off-screen); at 1440 it is
  1012 against 1444 (4 off-screen). Its horizontal scrollbar occupies 0 px of height, so no
  track is visible until the pane is already being scrolled.
- `landing`'s marquee (`#ticker.ticker-track`, 2605 px wide) overflows its own
  `overflow: hidden` band by design; it does not move the page.

## Findings

1. **Spacing has no rhythm** — 188 of 304 px values (61.8%) sit off the 4/8/12/16/24/32/48
   scale the tokens declare, and 6px appears 42 times (`styles.css:62,269,441,537,756,785,911,917,941,969,1013,1043,1062,1063,1133`).
   32px and 48px are never used, and `var(--space-*)` is referenced 0 times, so the scale exists
   only in `tokens.css:6-13`. Impact: **slows** (every new panel re-invents its own padding).
2. **Nineteen type sizes, five of them under 12px** — 11px×25, 13px×18, 11.5px×13, down to
   9.5px for the scenario stance (`styles.css:798`), and 13.5px for the tab labels
   (`styles.css:159`). `var(--font-*)` is referenced 0 times (`tokens.css:15-21`). Impact:
   **slows** (dense tables at 11px, a 9.5px label).
3. **Two colour palettes and 31 colours outside tokens** — `tokens.css:2-3` says nothing else
   defines a raw colour, but `landing.css:1-17` declares 13 colour tokens of its own (`--bg`,
   `--bg2`, `--card`, `--card2`, `--line`, `--line2`, `--txt`, `--mut`, `--mut2`, `--green`,
   `--red`, `--blue`, `--amber`), shares only `--bg` and `--mono` with `tokens.css`, and picks
   different values for the same ideas (`--bg` #0a0d12 vs #0b0e14; loss red #ef4444 vs
   #ea3943). 31 distinct hex values live outside `tokens.css`. Impact: **misleads** (a token
   change silently skips the landing page).
4. **Touch targets are half size** — 124 of 210 interactive elements at 360 px are under
   44 in one dimension, 61 under WCAG 2.5.8's 24 px. The smallest are the follow buttons
   (37×18 for XOM, 20×18 for the sector "+", `styles.css:1499-1508`), the inspector close
   (21×19, `styles.css:657-662`), desk chips (20 px, `styles.css:1568-1575`, `1626-1633`) and
   the filter pills (25 px, `styles.css:274-283`). Impact: **blocks use** on touch.
5. **Four contrast failures** — `--down` on `--panel` 4.44:1 (negative numbers, `.down`
   `styles.css:39-41`), white on `--accent` 3.68:1 for 11.5px pill text
   (`styles.css:287-291`), `--accent` on `--accent-soft` 4.05:1 for the chain badge
   (`styles.css:345-352`), landing `--mut2` on `--card` 3.29:1 for 11–12px captions
   (`landing.css:10`, used at `landing.css:278-283,469-474,624-628`). The chart palette passes
   3:1 everywhere (chart-1 is 3.48:1). Impact: **slows** (low-vision readers).
6. **The market tape hides most of itself** — 9 of 11 tiles are outside the 288 px pane at
   360 and 4 of 11 at 1440, with no persistent scrollbar (`styles.css:1385-1390`). INDEX.md
   names the 360 px case for #tickers; the measurement shows it is not only a 360 px problem.
   Impact: **misleads** (the tape looks complete).
7. **The mobile refresh button sits on content** — `.refresh` is `position: fixed` at
   right 12 / bottom 64, 48×48 (`mobile.css:45-58`), and overlaps the last filter row and
   feed rows at 360 (`before/today-360.png`, `before/desk-360.png`). Impact: **blocks use**.
8. **A hidden block keeps a grid cell on the scenario page** — `.ev-host { display: block }`
   (`styles.css:359-362`) beats the `hidden` attribute, so at ≥1100 the scenario page renders
   in the 300 px rail with ~1100 px of empty space (`before/scenario-1440.png`). Impact:
   **blocks use** (the page looks broken at desktop width).

Not measured: the globe texture is blocked in the capture, so the globe panel reads dark and
its contents are not audited; 768 px tap targets were not collected (the row asks 360 and
1440); component fills set inline by TS (verdict and stance badges) are not contrast-checked;
inline text links are listed at their text box (17–35 px tall) even though WCAG 2.5.8 exempts
links inside a sentence.
