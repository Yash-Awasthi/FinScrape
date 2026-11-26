import { afterEach, describe, expect, it, vi } from "vite-plus/test";

import type { EventOut, Watchlist } from "../api";
import { positions } from "../positions";
import { desk } from "../watchlist";
import { DeskPanel, ExposurePanel } from "./desk";

vi.mock("../api", () => ({
  api: {
    watchlistFeed: vi.fn(async () => []),
    outcomes: vi.fn(async () => []),
  },
}));

vi.mock("../watchlist", () => ({
  STARTERS: { Energy: [{ kind: "sector", value: "energy" }] },
  apiKey: () => "",
  createStarter: vi.fn(async () => null),
  desk: vi.fn(async () => null),
  setApiKey: vi.fn(),
  unfollow: vi.fn(async () => {}),
}));

vi.mock("../positions", () => ({
  positions: vi.fn(() => []),
  addPosition: vi.fn(),
  removePosition: vi.fn(),
}));

// setContent paints on the next animation frame.
const painted = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

const event = (overrides: Partial<EventOut> = {}): EventOut => ({
  id: 1,
  subject: "Strait closed to tankers",
  event_type: "shipping",
  verdict: "OBSERVE",
  impact_direction: "down",
  signal_score: 2,
  confidence: 0.6,
  reasoning: "",
  magnitude: "moderate",
  novelty: "new",
  actionability: "watch",
  sector_impact: "transport",
  tickers: ["XOM"],
  sources: [],
  articles: [],
  affected_entities: [],
  second_order_effects: [],
  key_metrics: {},
  lat: null,
  lon: null,
  timestamp: "2026-01-02T10:00:00Z",
  created_at: "2026-01-02T10:05:00Z",
  ...overrides,
});

const watchlist = (overrides: Partial<Watchlist> = {}): Watchlist => ({
  id: 1,
  name: "My Desk",
  created_at: "2026-01-02T10:00:00Z",
  items: [{ id: 1, kind: "ticker", value: "XOM" }],
  ...overrides,
});

afterEach(() => vi.clearAllMocks());

describe("DeskPanel advice", () => {
  it("carries the note when no watchlist exists", async () => {
    vi.mocked(desk).mockResolvedValue(null);
    vi.mocked(positions).mockReturnValue([]);
    const panel = new DeskPanel(() => {});
    await panel.load();
    await painted();
    expect(panel.body.textContent).toContain("Not financial advice.");
    expect(panel.body.querySelectorAll(".disclaimer")).toHaveLength(1);
  });

  it("carries the note once when a list exists", async () => {
    vi.mocked(desk).mockResolvedValue(watchlist());
    vi.mocked(positions).mockReturnValue([]);
    const panel = new DeskPanel(() => {});
    await panel.load();
    await painted();
    expect(panel.body.textContent).toContain("Not financial advice.");
    expect(panel.body.querySelectorAll(".disclaimer")).toHaveLength(1);
  });
});

describe("ExposurePanel advice", () => {
  it("labels the tally as exposure, not advice", async () => {
    vi.mocked(positions).mockReturnValue([{ symbol: "XOM", quantity: 10, cost_basis: 90 }]);
    const panel = new ExposurePanel();
    panel.update([event()]);
    await painted();
    expect(panel.body.textContent).toContain("Not financial advice.");
    expect(panel.body.textContent).toContain("exposure only");
    const note = panel.body.querySelector(".disclaimer");
    expect(note?.textContent).toContain("Not financial advice.");
    expect(note?.textContent).toContain("Exposure only");
  });
});
