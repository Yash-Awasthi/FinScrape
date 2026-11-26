import { afterEach, describe, expect, it, vi } from "vite-plus/test";

import type { DashboardStats } from "../api";
import { Freshness } from "./freshness";

const NOW = Date.parse("2026-01-02T12:00:00Z");

function stats(last: string | null, interval?: number): DashboardStats {
  return {
    total_events: 4,
    by_verdict: {},
    last_update: last,
    ...(interval === undefined ? {} : { ingest_interval_minutes: interval }),
  };
}

function mount(s: DashboardStats): Freshness {
  const f = new Freshness();
  document.body.append(f.el);
  f.update(s);
  return f;
}

afterEach(() => {
  vi.useRealTimers();
  document.body.replaceChildren();
});

describe("Freshness", () => {
  it("shows a recent ingest without a stale warning", () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    const f = mount(stats("2026-01-02T11:57:00Z"));
    expect(f.el.textContent).toContain("last ingest 11:57 UTC");
    expect(f.el.textContent).toContain("3m ago");
    expect(f.el.textContent).toContain("next expected by 12:12 UTC");
    expect(f.el.classList.contains("stale")).toBe(false);
    f.destroy();
  });

  it("warns when the last ingest is older than three intervals", () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    const f = mount(stats("2026-01-02T11:14:00Z", 15));
    expect(f.el.textContent).toContain("stale: no ingest for 46m, expected every 15m");
    expect(f.el.classList.contains("stale")).toBe(true);
    f.destroy();
  });

  it("says so when no ingest was ever recorded", () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    const f = mount(stats(null));
    expect(f.el.textContent).toContain("no ingest recorded yet");
    f.destroy();
  });

  it("falls back to a 15m cadence when the server omits it", () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    const f = mount(stats("2026-01-02T11:57:00Z"));
    expect(f.el.textContent).toContain("worker runs every 15m");
    f.destroy();
  });

  it("recomputes the age on its timer", () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    const f = mount(stats("2026-01-02T11:57:00Z"));
    vi.advanceTimersByTime(60_000);
    expect(f.el.textContent).toContain("4m ago");
    f.destroy();
  });
});
