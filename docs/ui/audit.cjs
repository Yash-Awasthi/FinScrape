// UI audit: measures spacing, type, colour, tap targets, contrast and horizontal
// overflow at commit 654a3ef (the "before" baseline), and prints every number it uses.
//
//   node docs/ui/audit.cjs                 # CSS/token sections only
//   node docs/ui/audit.cjs --dist=<dir>    # + live tap-target and overflow measurement
//
// The live half needs a build of 654a3ef served with the fixtures in docs/ui/serve.cjs.
// Build one outside the worktree (the worktree has other in-flight edits):
//
//   git archive 654a3ef web | tar -x -C /tmp/base
//   mklink /J \tmp\base\web\node_modules <repo>\web\node_modules   (or copy it)
//   cd /tmp/base/web && npm run build
//   node docs/ui/audit.cjs --dist=/tmp/base/web/dist
//
// Zero dependencies except @playwright/test, which the live half reuses from web/.
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const { readFileSync } = fs;

const COMMIT = process.env.AUDIT_COMMIT || "654a3ef";
const REPO = path.resolve(__dirname, "../..");
const CSS_FILES = [
  "web/src/styles.css",
  "web/src/landing/landing.css",
  "web/src/tokens.css",
  "web/src/app/mobile.css",
  "web/src/app/motion.css",
  "web/src/components/freshness.css",
];
const SPACING_SCALE = [4, 8, 12, 16, 24, 32, 48];
const TYPE_SCALE = [12, 14, 16, 20, 24, 32];

const distArg = process.argv.find((a) => a.startsWith("--dist="));
const DIST = distArg ? distArg.slice("--dist=".length) : null;
const only = process.argv.find((a) => a.startsWith("--only="));

// --- sources ----------------------------------------------------------------

const css = {};
for (const file of CSS_FILES) {
  // AUDIT_COMMIT=WORKTREE reads the files as authored on disk, for a before/after run
  // in the same sitting as the fix.
  css[file] =
    COMMIT === "WORKTREE"
      ? readFileSync(path.join(REPO, file), "utf8")
      : execFileSync("git", ["show", `${COMMIT}:${file}`], {
          cwd: REPO,
          encoding: "utf8",
          maxBuffer: 8 << 20,
        });
}

const lines = (file) => css[file].split("\n");
const h = (title) => console.log(`\n## ${title}`);
const num = (n, d = 0) => n.toFixed(d);

// --- 1. spacing -------------------------------------------------------------

const SPACE_PROPS =
  /^\s*(padding|margin|gap|inset|top|right|bottom|left)(-(top|right|bottom|left|inline|block|x|y))?\s*:\s*([^;]+);/;

function spacing() {
  const hits = [];
  for (const file of ["web/src/styles.css", "web/src/landing/landing.css"]) {
    lines(file).forEach((text, i) => {
      const m = SPACE_PROPS.exec(text);
      if (!m) return;
      const raw = m[4];
      if (/var\(|calc\(|clamp\(/.test(raw)) {
        hits.push({ file, line: i + 1, raw: raw.trim(), value: null, prop: m[1] });
        return;
      }
      for (const pm of raw.matchAll(/(-?\d*\.?\d+)px/g)) {
        hits.push({ file, line: i + 1, raw: raw.trim(), value: Number(pm[1]), prop: m[1] });
      }
    });
  }
  const px = hits.filter((x) => x.value !== null);
  const hist = new Map();
  for (const x of px) hist.set(x.value, (hist.get(x.value) || 0) + 1);
  const sorted = [...hist.entries()].sort((a, b) => a[0] - b[0]);
  const off = px.filter((x) => !SPACING_SCALE.includes(x.value));
  const offDecls = hits.filter((x) => x.value !== null && !SPACING_SCALE.includes(x.value));

  h("1. spacing: px values in padding/margin/gap/inset/top/right/bottom/left");
  console.log(`files: web/src/styles.css, web/src/landing/landing.css (at ${COMMIT})`);
  console.log(`declarations with px: ${px.length}   distinct values: ${hist.size}`);
  console.log(`histogram: ${sorted.map(([v, c]) => `${v}:${c}`).join("  ")}`);
  console.log(
    `off the 4/8/12/16/24/32/48 scale: ${off.length} of ${px.length} (${num((100 * off.length) / px.length, 1)}%)`,
  );
  const offHist = new Map();
  for (const x of off) offHist.set(x.value, (offHist.get(x.value) || 0) + 1);
  console.log(
    `off-scale values by frequency: ${[...offHist.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([v, c]) => `${v}:${c}`)
      .join("  ")}`,
  );
  // Offsets (top/right/bottom/left/inset) are positioning, not rhythm; separate them.
  const rhythm = hits.filter((x) => x.value !== null && /^(padding|margin|gap)/.test(x.prop || ""));
  const rhythmOff = rhythm.filter((x) => !SPACING_SCALE.includes(x.value));
  console.log(
    `rhythm only (padding/margin/gap): ${rhythm.length} px values, off-scale ${rhythmOff.length} (${num((100 * rhythmOff.length) / rhythm.length, 1)}%)`,
  );
  // The token file promises the scales; count how often the scales are actually used.
  const uses = (prefix, files = ["web/src/styles.css", "web/src/landing/landing.css"]) =>
    files.reduce((n, f) => n + (css[f].match(new RegExp(`var\\(${prefix}`, "g")) || []).length, 0);
  console.log(`uses of var(--space-*): ${uses("--space-")}   var(--font-*): ${uses("--font-")}   var(--radius-*): ${uses("--radius-")}   var(--<colour>): ${uses("--(bg|panel|text|muted|accent|up|down|warn|border|chart|mono)")}`);
  const radii = new Set();
  for (const f of ["web/src/styles.css", "web/src/landing/landing.css"]) {
    for (const m of css[f].matchAll(/border-radius:\s*([^;]+);/g)) radii.add(m[1].trim());
  }
  console.log(`distinct border-radius values: ${radii.size}   ${[...radii].join(" ")}`);
  console.log("top offenders (file:line  declaration; most frequent off-scale value first):");
  const declined = new Map();
  for (const x of offDecls) {
    const key = `${x.file}:${x.line}  ${x.prop}: ${x.raw}`;
    declined.set(key, { n: (declined.get(key)?.n || 0) + 1, v: x.value });
  }
  const freq = new Map();
  for (const x of off) freq.set(x.value, (freq.get(x.value) || 0) + 1);
  [...declined.entries()]
    .sort((a, b) => freq.get(b[1].v) - freq.get(a[1].v) || a[1].n - b[1].n)
    .slice(0, 16)
    .forEach(([k]) => console.log(`  ${k}`));
  return { total: px.length, distinct: hist.size, off: off.length, offDecls, rhythm };
}

// --- 2. type ----------------------------------------------------------------

function type() {
  const sizes = [];
  const families = [];
  const weights = [];
  for (const file of ["web/src/styles.css", "web/src/landing/landing.css"]) {
    lines(file).forEach((text, i) => {
      let m = /^\s*font-size\s*:\s*([^;]+);/.exec(text);
      if (m) {
        const raw = m[1].trim();
        if (/px$/.test(raw)) sizes.push({ file, line: i + 1, raw, px: Number(raw.replace("px", "")) });
        else if (/rem$/.test(raw)) sizes.push({ file, line: i + 1, raw, px: Number(raw.replace("rem", "")) * 16 });
        else sizes.push({ file, line: i + 1, raw, px: /em$/.test(raw) ? null : null });
      }
      m = /^\s*font-family\s*:\s*([^;]+);/.exec(text);
      if (m) families.push({ file, line: i + 1, raw: m[1].trim() });
      m = /^\s*font-weight\s*:\s*([^;]+);/.exec(text);
      if (m) weights.push(m[1].trim());
      // font shorthand (styles.css:11 sets 14px/1.45 in one declaration)
      m = /^\s*font\s*:\s*([^;]+);/.exec(text);
      if (m && /(\d*\.?\d+)(px|rem)/.test(m[1])) {
        const pm = /(\d*\.?\d+)(px|rem)\//.exec(m[1]);
        if (pm) sizes.push({ file, line: i + 1, raw: `font shorthand ${m[1].trim()}`, px: Number(pm[1]) * (pm[2] === "rem" ? 16 : 1) });
      }
    });
  }
  const px = sizes.filter((s) => s.px !== null);
  const hist = new Map();
  for (const s of px) hist.set(s.px, (hist.get(s.px) || 0) + 1);
  const off = px.filter((s) => !TYPE_SCALE.includes(s.px));

  h("2. type: font-size, font-family, weights");
  console.log(`font-size declarations (resolved to px): ${px.length}   distinct: ${hist.size}`);
  console.log(
    `histogram: ${[...hist.entries()].sort((a, b) => a[0] - b[0]).map(([v, c]) => `${v}:${c}`).join("  ")}`,
  );
  console.log(`off the 12/14/16/20/24/32 scale: ${off.length} of ${px.length} (${num((100 * off.length) / px.length, 1)}%)`);
  const offHist = new Map();
  for (const s of off) offHist.set(s.px, (offHist.get(s.px) || 0) + 1);
  console.log(
    `off-scale sizes: ${[...offHist.entries()].sort((a, b) => b[1] - a[1]).map(([v, c]) => `${v}:${c}`).join("  ")}`,
  );
  console.log("off-scale declarations (file:line value):");
  off.slice(0, 18).forEach((s) => console.log(`  ${s.file}:${s.line}  ${s.raw}`));
  console.log(`font-family declarations: ${families.length}`);
  families.forEach((f) => console.log(`  ${f.file}:${f.line}  ${f.raw}`));
  const wHist = new Map();
  for (const w of weights) wHist.set(w, (wHist.get(w) || 0) + 1);
  console.log(`font-weight declarations: ${weights.length}   ${[...wHist.entries()].map(([v, c]) => `${v}:${c}`).join("  ")}`);
  const nonPx = sizes.filter((s) => s.px === null);
  console.log(`non-px font-size declarations: ${nonPx.length}   ${nonPx.map((s) => `${s.file.split("/").pop()}:${s.line} ${s.raw}`).join("  ")}`);
  return { total: px.length, distinct: hist.size, off: off.length };
}

// --- 3. colours -------------------------------------------------------------

const toHex = (s) => {
  let x = s.toLowerCase().slice(1);
  if (x.length === 3 || x.length === 4) x = x.slice(0, 3).split("").map((c) => c + c).join("");
  if (x.length === 8) x = x.slice(0, 6); // ignore alpha for distinctness
  return "#" + x;
};

function colours() {
  const perFile = new Map();
  let rgbCount = 0;
  let hexRefs = 0;
  for (const file of CSS_FILES) {
    const set = new Set();
    const body = css[file];
    // 3-, 6- and 8-digit hex only (4/5-digit arrive as 3+alpha, handled by toHex).
    for (const m of body.matchAll(/#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b/g)) {
      set.add(toHex(m[0]));
      hexRefs += 1;
    }
    rgbCount += (body.match(/\brgba?\(/g) || []).length;
    rgbCount += (body.match(/\bhsla?\(/g) || []).length;
    const named = (body.match(/:\s*(#fff|#000)\b/g) || []).length;
    perFile.set(file, { set, named });
  }
  const all = new Set();
  for (const { set } of perFile.values()) for (const c of set) all.add(c);
  const outside = new Set();
  for (const [file, { set }] of perFile) {
    if (file === "web/src/tokens.css") continue;
    for (const c of set) outside.add(c);
  }
  const tokens = perFile.get("web/src/tokens.css").set;

  h("3. colour count across web/src CSS");
  console.log(`files (${COMMIT}): ${CSS_FILES.join(", ")}`);
  console.log(`hex literals: ${hexRefs} uses   distinct hex: ${all.size}`);
  console.log(`distinct hex outside tokens.css: ${outside.size}`);
  console.log(`rgb()/rgba()/hsl() calls: ${rgbCount}`);
  console.log(`tokens.css distinct hex: ${tokens.size}`);
  for (const [file, { set }] of perFile) console.log(`  ${file}: ${set.size} distinct hex`);
  console.log(`hex outside tokens.css: ${[...outside].sort().join(" ")}`);
  return { distinct: all.size, outside: outside.size, rgb: rgbCount };
}

// --- 5. contrast ------------------------------------------------------------

function srgb(c) {
  const x = c / 255;
  return x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
}
function lum(hex) {
  const h = toHex(hex).slice(1);
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b);
}
function ratio(a, b) {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

function tokenMap() {
  const map = {};
  for (const m of css["web/src/tokens.css"].matchAll(/--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\s*;/g)) {
    map[m[1]] = m[2];
  }
  return map;
}

function contrast() {
  const t = tokenMap();
  const rows = [];
  for (const fg of ["text", "muted", "up", "down", "accent", "warn"]) {
    for (const bg of ["bg", "panel", "panel-2"]) rows.push([`--${fg}`, `--${bg}`, t[fg], t[bg]]);
  }
  for (let i = 1; i <= 7; i++) rows.push([`--chart-${i}`, "--panel", t[`chart-${i}`], t.panel]);

  h("5. contrast (WCAG 2.1, sRGB relative luminance)");
  console.log("pair".padEnd(24), "hex".padEnd(18), "ratio", " body4.5", " ui3.0");
  for (const [fg, bg, f, b] of rows) {
    const r = ratio(f, b);
    console.log(
      `${(fg + " on " + bg).padEnd(24)} ${(f + " / " + b).padEnd(18)} ${num(r, 2).padStart(5)}  ${r >= 4.5 ? "pass" : "FAIL"}    ${r >= 3 ? "pass" : "FAIL"}`,
    );
  }
  const extra = [
    // `.ffilter.active` fills with --accent-bg; older palettes only had --accent.
    [
      "#fff on --accent-bg (.ffilter.active)",
      "#ffffff",
      t["accent-bg"] ?? t.accent,
    ],
    ["--muted on --panel-head", t.muted, t["panel-head"]],
    ["--text on --panel-head", t.text, t["panel-head"]],
    ["--accent on --accent-soft (.chain-badge)", t.accent, t["accent-soft"]],
  ];
  for (const [label, f, b] of extra) {
    if (!f || !b) {
      console.log(`${label.padEnd(24)} (token missing from tokens.css)`);
      continue;
    }
    const r = ratio(f, b);
    console.log(
      `${label.padEnd(24)} ${(f + " / " + b).padEnd(18)} ${num(r, 2).padStart(5)}  ${r >= 4.5 ? "pass" : "FAIL"}    ${r >= 3 ? "pass" : "FAIL"}`,
    );
  }

  // landing.css once carried a second palette; if it still declares one, measure it.
  const l = {};
  for (const m of css["web/src/landing/landing.css"].matchAll(/--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\s*;/g)) l[m[1]] = m[2];
  const lrows = [
    ["landing --txt on --bg", l.txt, l.bg],
    ["landing --mut on --bg", l.mut, l.bg],
    ["landing --mut2 on --bg", l.mut2, l.bg],
    ["landing --mut2 on --card", l.mut2, l.card],
    ["landing --green on --bg", l.green, l.bg],
    ["landing --red on --bg", l.red, l.bg],
    ["landing --blue on --bg", l.blue, l.bg],
  ];
  if (!Object.keys(l).length) {
    console.log(
      "landing.css imports ../tokens.css and declares no second palette: the pairs above cover it",
    );
  } else {
    console.log("landing.css second palette (overrides the same names):");
    for (const [label, f, b] of lrows) {
      // A partial palette leaves one side undefined; report the gap, never crash.
      if (!f || !b) {
        console.log(`${label.padEnd(24)} (token is not a hex literal in landing.css)`);
        continue;
      }
      const r = ratio(f, b);
      console.log(
        `${label.padEnd(24)} ${(f + " / " + b).padEnd(18)} ${num(r, 2).padStart(5)}  ${r >= 4.5 ? "pass" : "FAIL"}    ${r >= 3 ? "pass" : "FAIL"}`,
      );
    }
  }
  return { rows: rows.length };
}

// --- 6. media queries and declared mobile behaviour -------------------------

function overflowCss() {
  h("6a. media queries and declared mobile behaviour");
  const bps = new Map();
  for (const file of CSS_FILES) {
    lines(file).forEach((text, i) => {
      const m = /@media\s*([^{]+)\{/.exec(text);
      if (!m) return;
      const q = m[1].trim();
      if (!bps.has(q)) bps.set(q, []);
      bps.get(q).push(`${file}:${i + 1}`);
    });
  }
  for (const [q, at] of bps) console.log(`  ${q}   ${at.join(" ")}`);
  const find = (re, file) => lines(file).filter((t) => re.test(t)).length;
  console.log(`breakpoints in use: ${bps.size} distinct queries`);
  const m1100 = blocks("web/src/styles.css").filter((b) => /1100/.test(b.media || ""));
  console.log(`rules inside @media (max-width:1100): ${m1100.length}   ${m1100.map((b) => b.sel).join(" | ")}`);
  console.log(`\`.app-grid\` rules inside any media query: ${CSS_FILES.map((f) => blocks(f).filter((b) => /\.app-grid/.test(b.sel) && b.media).length).reduce((a, b) => a + b, 0)} (base rule only sets min-width:0)`);
  console.log(`\`.app-main\` collapse at 1100: ${/\.app-main[^{]*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\);/.test(css["web/src/styles.css"].split("@media (max-width: 1100px)")[1] || "") ? "yes" : "no"}`);
  console.log(`bottom nav (fixed .tabs at max-width:700): ${/@media \(max-width: 700px\)[\s\S]*?\.head-left \.tabs \{[\s\S]*?position: fixed/.test(css["web/src/app/mobile.css"]) ? "yes, web/src/app/mobile.css" : "no"}`);
  const ox = [];
  for (const file of CSS_FILES) {
    lines(file).forEach((t, i) => {
      if (/overflow-x\s*:\s*auto/.test(t)) ox.push(`${file}:${i + 1}`);
    });
  }
  console.log(`overflow-x:auto declarations: ${ox.length}   ${ox.join(" ")}`);
  console.log("table overflow in CSS: none; at <=700px mobile.css sets table-layout:fixed and white-space:normal");
}

// --- 4. tap targets ---------------------------------------------------------

// Minimal block reader: enough for these hand-written stylesheets. @media blocks are
// recursed into and labelled, so a 700px override is not mistaken for a base rule.
function parseBlocks(text, media, file, out) {
  let i = 0;
  while (i < text.length) {
    const open = text.indexOf("{", i);
    if (open < 0) break;
    const sel = text.slice(i, open).trim();
    let depth = 1;
    let j = open + 1;
    while (j < text.length && depth > 0) {
      if (text[j] === "{") depth += 1;
      else if (text[j] === "}") depth -= 1;
      j += 1;
    }
    const inner = text.slice(open + 1, j - 1);
    if (sel.startsWith("@media")) {
      parseBlocks(inner, (media ? media + " " : "") + sel.replace(/\s+/g, " "), file, out);
    } else if (!sel.startsWith("@")) {
      out.push({ file, sel: sel.replace(/\s+/g, " "), decl: inner, media });
    }
    i = j;
  }
}

function blocks(file) {
  const out = [];
  parseBlocks(css[file].replace(/\/\*[\s\S]*?\*\//g, ""), "", file, out);
  return out;
}

const INTERACTIVE =
  /(^|[\s,>])(a|button|input|select|\.btn|\.tabs|\.refresh|\.ffilter|\.follow|\.followed|\.held|\.starter|\.sc-tk|\.cal \.day|\.sug-row|\.mkt-tile|\.src-row|\.call-list li|\.story-toggle|\.ai-btn|\.candles-form|\.desk-key|\.palette-item|\.chip|\.nav-links)/;

function declaredBoxes() {
  h("4a. declared boxes of interactive elements (from CSS)");
  for (const file of ["web/src/styles.css", "web/src/app/mobile.css", "web/src/landing/landing.css"]) {
    for (const b of blocks(file)) {
      if (!INTERACTIVE.test(b.sel)) continue;
      const bits = [];
      for (const prop of ["height", "min-height", "max-height", "padding", "font-size", "line-height", "width"]) {
        const m = new RegExp(`(^|;)\\s*${prop}\\s*:\\s*([^;]+)`).exec(b.decl);
        if (m) bits.push(`${prop}: ${m[2].trim()}`);
      }
      if (!bits.length) continue;
      console.log(`  ${b.file}${b.media ? ` ${b.media.replace("@media ", "")}` : ""}: ${b.sel}`);
      console.log(`    ${bits.join("  |  ")}`);
    }
  }
  const hts = [];
  for (const file of CSS_FILES) {
    lines(file).forEach((t, i) => {
      const m = /^\s*(min-height|height)\s*:\s*(\d+(?:\.\d+)?px)\s*;/.exec(t);
      if (m) hts.push({ v: Number(m[2].replace("px", "")), at: `${file}:${i + 1}` });
    });
  }
  const small = hts.filter((x) => x.v < 44);
  console.log(`\ndeclared height/min-height values under 44px: ${small.length} of ${hts.length}`);
  console.log(`  ${small.map((x) => `${x.v}px ${x.at}`).join("  ")}`);
}


async function live() {
  const { chromium } = require(path.join(REPO, "web/node_modules/@playwright/test"));
  const Module = require("node:module");
  const serveFile = path.join(__dirname, "serve.cjs");
  const src = fs
    .readFileSync(serveFile, "utf8")
    .replace('path.resolve(__dirname, "../../web/dist")', JSON.stringify(path.resolve(DIST)));
  const m = new Module(serveFile, module);
  m.filename = serveFile;
  m.paths = Module._nodeModulePaths(__dirname);
  m._compile(src, serveFile);
  const { start, stop, EVENTS } = m.exports;

  const CHROME =
    process.env.CHROME_BIN ||
    "C:/Users/Yash/AppData/Local/ms-playwright/chromium-1255/chrome-win64/chrome.exe";
  const ORIGIN = "http://127.0.0.1:8099";

  const SURFACES = [
    { name: "landing", url: "/", ready: ["#hero-stats"] },
    { name: "today", url: "/app/#today", ready: ['[data-id="feed"] tr[data-event-id]'] },
    { name: "desk", url: "/app/#desk", ready: ['[data-id="desk"] .desk-feed tr[data-event-id]'], setup: 'window.dispatchEvent(new CustomEvent("worldfin:followed"))' },
    { name: "record", url: "/app/#record", ready: ['[data-id="accuracy"] .acc'] },
    { name: "sources", url: "/app/#sources", ready: ['[data-id="sources"] .src-row'] },
    { name: "event", url: "/app/#/app/event/1", ready: [".event-page"] },
    { name: "scenario", url: "/app/#/app/scenario/s1", ready: [".scenario-page"] },
    { name: "ticker", url: "/app/#tickers", ready: ['[data-id="candles"] .candles-svg'] },
    { name: "council", url: "/app/#today", ready: ['[data-id="feed"] tr[data-event-id]'], select: true },
  ];

  const collect = () => {
    const seen = new Set();
    const out = [];
    const cand = new Set();
    for (const sel of [
      "a[href]",
      "button",
      "input:not([type=hidden])",
      "select",
      "textarea",
      "[role=button]",
      "summary",
    ]) {
      for (const el of document.querySelectorAll(sel)) cand.add(el);
    }
    for (const el of document.querySelectorAll("*")) {
      const cs = getComputedStyle(el);
      if (cs.cursor !== "pointer") continue;
      // cursor is inherited: only the element that owns it is the target, and only for
      // tags that plausibly carry a click handler (rows, tiles, chips).
      let p = el.parentElement;
      let inherited = false;
      while (p && p !== document.documentElement) {
        if (getComputedStyle(p).cursor === "pointer") {
          inherited = true;
          break;
        }
        p = p.parentElement;
      }
      if (inherited) continue;
      if (!/^(LI|TR|DIV|SPAN|LABEL|BUTTON|A|FIGCAPTION|ARTICLE)$/.test(el.tagName)) continue;
      cand.add(el);
    }
    for (const el of cand) {
      if (seen.has(el)) continue;
      seen.add(el);
      const r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) continue;
      if (r.bottom < -20) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === "hidden" || cs.display === "none" || Number(cs.opacity) === 0) continue;
      const panel = el.closest("[data-id]");
      const id = el.id ? `#${el.id}` : "";
      const cls = [...el.classList].slice(0, 3).map((c) => `.${c}`).join("");
      const sig = `${el.tagName.toLowerCase()}${id}${cls}${panel ? ` [data-id=${panel.getAttribute("data-id")}]` : ""}`;
      out.push({
        sig,
        w: Math.round(r.width),
        h: Math.round(r.height),
        text: (el.textContent || el.value || el.getAttribute("aria-label") || "").trim().slice(0, 22),
      });
    }
    return { elements: out, docW: document.documentElement.scrollWidth, innerW: window.innerWidth };
  };

  const overflowProbe = () => {
    const innerW = window.innerWidth;
    const bad = [];
    for (const el of document.querySelectorAll("body *")) {
      const cs = getComputedStyle(el);
      if (cs.position === "fixed" || cs.visibility === "hidden" || cs.display === "none") continue;
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.right <= innerW + 1) continue;
      const panel = el.closest("[data-id]");
      bad.push({
        sig: `${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""}${[...el.classList].slice(0, 3).map((c) => "." + c).join("")}${panel ? ` [data-id=${panel.getAttribute("data-id")}]` : ""}`,
        right: Math.round(r.right),
        w: Math.round(r.width),
      });
    }
    const tape = document.querySelector(".mkt-tape");
    return {
      docW: document.documentElement.scrollWidth,
      innerW,
      bad,
      tape: tape
        ? {
            scrollW: tape.scrollWidth,
            clientW: tape.clientWidth,
            tiles: tape.children.length,
            hBarPx: tape.offsetHeight - tape.clientHeight,
          }
        : null,
    };
  };

  await start().catch((e) => {
    if (!/EADDRINUSE/.test(e.message)) throw e;
  });
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const tap = { 360: [], 1440: [] };
  const tapKey = [];
  const of = { 360: [], 1440: [] };
  try {
    for (const surface of SURFACES) {
      for (const width of [360, 1440]) {
        const context = await browser.newContext({
          viewport: { width, height: 900 },
          deviceScaleFactor: 1,
          reducedMotion: "reduce",
        });
        await context.addInitScript(() => {
          try {
            localStorage.setItem(
              "worldfin.positions",
              JSON.stringify([
                { symbol: "XOM", quantity: 120, cost_basis: 104.2 },
                { symbol: "FRO", quantity: 300, cost_basis: 21.8 },
              ]),
            );
          } catch {
            /* storage blocked */
          }
        });
        const page = await context.newPage();
        await page.route("**/*", (route) =>
          new URL(route.request().url()).origin === ORIGIN ? route.continue() : route.abort(),
        );
        try {
          await page.routeWebSocket("**/api/ws", (ws) => {
            ws.send(
              JSON.stringify({
                type: "init",
                events: EVENTS,
                stats: {
                  total_events: 9842,
                  by_verdict: { INVEST: 2814, OBSERVE: 3902, CAUTIOUS: 2210, PULL_OUT: 916 },
                  last_update: new Date().toISOString(),
                },
              }),
            );
          });
        } catch {
          /* older playwright: REST fixtures still render the page */
        }
        await page.goto(ORIGIN + surface.url, { waitUntil: "load", timeout: 45_000 });
        if (surface.setup) await page.evaluate(surface.setup);
        for (const sel of surface.ready) {
          await page.locator(sel).first().waitFor({ state: "visible", timeout: 30_000 });
        }
        await page.waitForTimeout(400);
        if (surface.select) {
          await page.locator('[data-id="feed"] .row-meta').first().click();
          await page.locator(".inspector .verdict-badge").first().waitFor({ state: "visible", timeout: 15_000 });
          await page.getByRole("button", { name: "Ask the analyst council" }).click();
          await page.waitForFunction(
            () => [...document.querySelectorAll(".inspector .ai-out")].some((n) => /consensus|dissent|agreement/i.test(n.textContent || "")),
            null,
            { timeout: 20_000 },
          );
        }
        const res = await page.evaluate(collect);
        tap[width].push({ surface: surface.name, ...res });
        const key = await page.evaluate(() => {
          const out = [];
          for (const sel of [".tabs a", ".refresh", ".mkt-tile", ".btn", ".ffilter", ".follow", ".day", ".ai-btn", ".sc-tk", ".inspector-close", ".story-toggle", "input", "a.ev-back", ".src-row", ".call-list li"]) {
            const el = document.querySelector(sel);
            if (!el) continue;
            const r = el.getBoundingClientRect();
            if (r.width < 1 || r.height < 1) continue;
            out.push({ sel, w: Math.round(r.width), h: Math.round(r.height), n: document.querySelectorAll(sel).length });
          }
          return out;
        });
        for (const k of key) {
          const hit = tapKey.find((t) => t.width === width && t.sel === k.sel && t.surface === surface.name);
          if (!hit) tapKey.push({ width, surface: surface.name, ...k });
          else if (k.n > hit.n) Object.assign(hit, k);
        }
        of[width].push({ surface: surface.name, ...(await page.evaluate(overflowProbe)) });
        await context.close();
      }
    }
  } finally {
    await browser.close();
    await stop();
  }

  h(`4b. tap targets (live, ${COMMIT} build at ${DIST})`);
  for (const width of [360, 1440]) {
    const all = tap[width].flatMap((s) => s.elements.map((e) => ({ ...e, surface: s.surface })));
    const fail = all.filter((e) => e.w < 44 || e.h < 44);
    const short = fail.filter((e) => e.h < 44);
    const narrow = fail.filter((e) => e.w < 44);
    const both = fail.filter((e) => e.h < 44 && e.w < 44);
    const under24 = fail.filter((e) => e.h < 24 || e.w < 24);
    const groups = new Map();
    for (const e of fail) {
      const g = groups.get(e.sig) || { ...e, n: 0, minW: e.w, maxW: e.w, minH: e.h, surfaces: new Set() };
      g.n += 1;
      g.minW = Math.min(g.minW, e.w);
      g.maxW = Math.max(g.maxW, e.w);
      g.minH = Math.min(g.minH, e.h);
      g.surfaces.add(e.surface);
      groups.set(e.sig, g);
    }
    const sorted = [...groups.values()].sort((a, b) => a.minH - b.minH || a.minW - b.minW);
    console.log(
      `\n@${width}px: ${all.length} interactive elements; ${fail.length} under 44 in width or height ` +
        `(height<44: ${short.length}, width<44: ${narrow.length}, both: ${both.length}; also under WCAG 2.5.8's 24px: ${under24.length}); ${sorted.length} distinct selectors fail`,
    );
    for (const g of sorted.slice(0, 30)) {
      const size = `h=${g.minH} w=${g.minW}${g.maxW > g.minW ? "-" + g.maxW : ""}`;
      console.log(
        `  ${size.padEnd(22)}${g.sig.padEnd(46)}x${String(g.n).padStart(3)}  ${[...g.surfaces].join(",")}  "${g.text}"`,
      );
    }
  }

  h("4c. key controls, measured (first box on the surface named)");
  for (const width of [360, 1440]) {
    const bySel = new Map();
    for (const k of tapKey.filter((t) => t.width === width)) {
      const prev = bySel.get(k.sel);
      if (!prev || k.n > prev.n) bySel.set(k.sel, k);
    }
    console.log(`  @${width}px`);
    for (const k of bySel.values()) {
      console.log(`    ${k.sel.padEnd(20)} ${String(k.w).padStart(4)}x${String(k.h).padEnd(4)} on ${k.surface} (n=${k.n})`);
    }
  }

  h("6b. horizontal overflow (live)");
  for (const width of [360, 1440]) {
    console.log(`\n@${width}px: view scrollWidth vs innerWidth`);
    for (const s of of[width]) {
      const extra = s.docW - s.innerW;
      console.log(
        `  ${s.surface.padEnd(9)} scrollWidth=${String(s.docW).padStart(5)}  innerWidth=${s.innerW}  over=${extra > 0 ? "+" + extra : "0"}` +
          (s.tape ? `  .mkt-tape ${s.tape.clientW}/${s.tape.scrollW}px, ${s.tape.tiles} tiles, h-scrollbar ${s.tape.hBarPx}px` : ""),
      );
      for (const b of s.bad.slice(0, 4)) console.log(`      past edge: ${b.sig} right=${b.right} w=${b.w}`);
    }
  }
  return { tap, of };
}

// --- run --------------------------------------------------------------------

(async () => {
  const parts = {};
  if (!only || only === "--only=spacing") parts.spacing = spacing();
  if (!only || only === "--only=type") parts.type = type();
  if (!only || only === "--only=colour") parts.colour = colours();
  if (!only || only === "--only=contrast") parts.contrast = contrast();
  if (!only || only === "--only=overflow") overflowCss();
  if (!only || only === "--only=boxes") declaredBoxes();
  if (DIST && (!only || only === "--only=live")) await live();
  if (!DIST) console.log("\n(live tap targets and overflow skipped: pass --dist=<build>/web/dist)");
  console.log("\ndone");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
