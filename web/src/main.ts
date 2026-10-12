import "./styles.css";

import { api } from "./api";
import { VIEWS, allPanelIds, isView, type ViewId } from "./app/variants";
import { Shell } from "./app/shell";
import { BreakingNewsBanner } from "./components/banner";
import { Inspector } from "./components/inspector";
import type { GlobeView } from "./globe/globe";
import type { EventOut } from "./api";
import { PanelLayoutManager } from "./panels/layout";
import { Panel } from "./panels/panel";
import {
  AccuracyPanel,
  CalendarPanel,
  CandlesPanel,
  CorrelationPanel,
  OutcomesPanel,
  PredictionPanel,
  ScenarioPanel,
  SectorPanel,
  SourceHealthPanel,
  StatsPanel,
  SuggestionsPanel,
} from "./panels/panels";
import { SignalFeedPanel } from "./panels/signal-feed";
import { Store } from "./state";
import { RealtimeClient, wsUrl, type WSMessage } from "./ws";

const store = new Store();
const inspector = new Inspector(() => store.select(null));
const banner = new BreakingNewsBanner();

const views = Object.entries(VIEWS).map(([id, v]) => ({ id, label: v.label }));
const shell = new Shell(
  () => void loadAll(),
  views,
  (id) => showView(id),
);
const layout = new PanelLayoutManager();

const feedPanel = new SignalFeedPanel((e) => store.select(e));
const globePanel = new Panel({ id: "globe", title: "Globe", w: 7, h: 9 });
const statsPanel = new StatsPanel();
const datesPanel = new CalendarPanel((day) => void loadDay(day));
const scenarioPanel = new ScenarioPanel();
const suggestionsPanel = new SuggestionsPanel();
const candlesPanel = new CandlesPanel(
  () => store.get().events,
  (e) => store.select(e),
);
const sectorPanel = new SectorPanel();
const accuracyPanel = new AccuracyPanel();
const predictionPanel = new PredictionPanel();
const outcomesPanel = new OutcomesPanel();
const sourceHealthPanel = new SourceHealthPanel();
const correlationPanel = new CorrelationPanel();

for (const p of [
  scenarioPanel,
  feedPanel,
  globePanel,
  statsPanel,
  datesPanel,
  suggestionsPanel,
  candlesPanel,
  sectorPanel,
  accuracyPanel,
  predictionPanel,
  outcomesPanel,
  sourceHealthPanel,
  correlationPanel,
]) {
  layout.add(p);
}
layout.checkViews(allPanelIds());

const app = document.getElementById("app")!;
shell.mount(app);
shell.bannerSlot.append(banner.el);
layout.mount(shell.grid);
shell.railSlot.append(inspector.el);

function showView(id: string): void {
  const view: ViewId = isView(id) ? id : "today";
  layout.applyVariant(VIEWS[view].slots);
  shell.setView(view);
  if (location.hash !== `#${view}`) history.replaceState(null, "", `#${view}`);
  // The globe measures its panel, which has no size while its view is hidden.
  if (view === "today") requestAnimationFrame(sizeGlobe);
}
window.addEventListener("hashchange", () => showView(location.hash.slice(1)));

// globe.gl (+three.js) is ~1.8MB — lazy chunk so the shell paints immediately.
let globe: GlobeView | null = null;
function sizeGlobe(): void {
  if (!globe) return;
  const r = globePanel.body.getBoundingClientRect();
  if (r.width && r.height) globe.resize(r.width, r.height);
}
window.addEventListener("resize", sizeGlobe);
void import("./globe/globe").then(({ GlobeView }) => {
  globePanel.body.replaceChildren();
  globe = new GlobeView(globePanel.body, (e) => store.select(e));
  sizeGlobe();
  globe.setEvents(store.get().events);
});

// The globe re-creates its meshes on setEvents — only feed it when the event
// array actually changed (loads / WS pushes), never on row clicks/selection.
let lastGlobeEvents: EventOut[] | null = null;
let lastSelectedId: number | null = null;
store.subscribe((s) => {
  shell.setConnection(s.connection);
  if (s.events !== lastGlobeEvents) {
    lastGlobeEvents = s.events;
    feedPanel.update(s.events);
    globe?.setEvents(s.events);
  }
  if (s.stats) statsPanel.update(s.stats);
  correlationPanel.update(s.correlations);
  banner.update(s.correlations);
  if (s.selected && s.selected.id !== lastSelectedId) {
    lastSelectedId = s.selected.id;
    inspector.show(s.selected);
  } else if (!s.selected && lastSelectedId !== null) {
    lastSelectedId = null;
    inspector.reset();
    feedPanel.clearActive();
  }
});

// j/k walks the feed, Esc clears. Ignored while typing or while the palette is open,
// so the command bar and the chart's symbol input keep their keys.
window.addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if ((e.target as HTMLElement | null)?.closest("input, textarea, select")) return;
  if (!document.querySelector(".palette.hidden")) return;
  if (e.key === "j") {
    e.preventDefault();
    feedPanel.moveSelection(1);
  } else if (e.key === "k") {
    e.preventDefault();
    feedPanel.moveSelection(-1);
  } else if (e.key === "Escape") {
    store.select(null);
  }
});

async function loadAll(): Promise<void> {
  // allSettled: one missing backend endpoint must never blank the whole load.
  const [events, stats, correlations, dates] = await Promise.allSettled([
    api.events({ limit: 200 }),
    api.stats(),
    api.correlations(),
    api.dates(),
  ]);
  if (events.status === "fulfilled") store.setEvents(events.value);
  if (stats.status === "fulfilled") store.setStats(stats.value);
  if (correlations.status === "fulfilled") store.setCorrelations(correlations.value);
  if (dates.status === "fulfilled") datesPanel.update(dates.value);
  // Momentum badges and storyline collapse need these before the feed's last render.
  const [suggestions, storylines] = await Promise.allSettled([
    api.suggestions(10),
    api.storylines(),
  ]);
  window.__wfSuggestions = (suggestions.status === "fulfilled" && suggestions.value) || [];
  window.__wfStorylines = (storylines.status === "fulfilled" && storylines.value) || [];
  feedPanel.update(store.get().events);
  // The chart opens on the most-covered ticker rather than a fixed symbol.
  const top = window.__wfSuggestions[0]?.ticker;
  if (top) candlesPanel.setSymbol(top);
  await Promise.allSettled([
    scenarioPanel.load(),
    suggestionsPanel.load(),
    candlesPanel.load(),
    sectorPanel.load(),
    accuracyPanel.load(),
    predictionPanel.load(),
    outcomesPanel.load(),
    sourceHealthPanel.load(),
  ]);
}

async function loadDay(day: string): Promise<void> {
  try {
    store.setEvents(await api.events({ date: day, limit: 200 }));
    store.setCorrelations(await api.correlations(day));
  } catch (err) {
    console.error("day load failed", err);
  }
}

function onMessage(msg: WSMessage): void {
  if (msg.type === "init" && msg.events) store.setEvents(msg.events);
  else if (msg.type === "new_events" && msg.events) store.addEvents(msg.events);
  if (msg.stats) store.setStats(msg.stats);
}

(window as unknown as { __wfEvents?: EventOut[] }).__wfEvents = [];
store.subscribe((s) => {
  (window as unknown as { __wfEvents?: EventOut[] }).__wfEvents = s.events;
});
// Any ticker chip opens the Tickers view with that symbol charted.
window.addEventListener("worldfin:select-symbol", () => showView("tickers"));
// Sector chips and source rows filter the feed, which lives on Today.
window.addEventListener("worldfin:select-sector", () => showView("today"));
window.addEventListener("worldfin:select-source", () => showView("today"));
window.addEventListener("worldfin:search-events", (e) => {
  const q = (e as CustomEvent<string>).detail;
  const hit = store
    .get()
    .events.find(
      (ev) =>
        ev.subject.toLowerCase().includes(q) || ev.tickers.some((t) => t.toLowerCase().includes(q)),
    );
  if (hit) {
    showView("today");
    store.select(hit);
  }
});
// The prediction panel's calibration grows as outcomes score themselves.
window.setInterval(() => {
  if (predictionPanel.el.offsetParent) void predictionPanel.load();
}, 60_000);
const rt = new RealtimeClient(wsUrl(), onMessage, (status) => store.setConnection(status));

showView(location.hash.slice(1));
void loadAll();
rt.connect();
