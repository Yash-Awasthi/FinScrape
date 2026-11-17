import { describe, expect, it, vi } from "vite-plus/test";
import type { DashboardStats } from "./api";
import { RefreshLoop } from "./live";

function stats(update: string | null): DashboardStats {
  return { total_events: 1, by_verdict: {}, last_update: update };
}

describe("RefreshLoop", () => {
  it("reloads when the API reports a newer write", async () => {
    const onChange = vi.fn(async () => {});
    const loop = new RefreshLoop(async () => stats("2026-01-01T10:00:00Z"), onChange);
    loop.note(stats("2026-01-01T09:00:00Z"));
    await loop.tick();
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(stats("2026-01-01T10:00:00Z"));
    // The new stamp is remembered: the same answer does not reload again.
    await loop.tick();
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("does nothing when the write stamp has not moved", async () => {
    const onChange = vi.fn(async () => {});
    const loop = new RefreshLoop(async () => stats("2026-01-01T10:00:00Z"), onChange);
    loop.note(stats("2026-01-01T10:00:00Z"));
    await loop.tick();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("reloads the first time an empty database gets a write", async () => {
    const onChange = vi.fn(async () => {});
    const loop = new RefreshLoop(async () => stats("2026-01-01T10:00:00Z"), onChange);
    loop.note(stats(null));
    await loop.tick();
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("skips hidden tabs", async () => {
    const fetchStats = vi.fn(async () => stats("2026-01-01T10:00:00Z"));
    const onChange = vi.fn(async () => {});
    const loop = new RefreshLoop(fetchStats, onChange, 60_000, () => false);
    await loop.tick();
    expect(fetchStats).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("retries a failed reload instead of advancing past it", async () => {
    const onChange = vi.fn(async () => {
      if (onChange.mock.calls.length === 1) throw new Error("offline");
    });
    const loop = new RefreshLoop(async () => stats("2026-01-01T10:00:00Z"), onChange);
    await loop.tick(); // throws inside, swallowed, stamp not advanced
    await loop.tick();
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it("collapses overlapping ticks to one request", async () => {
    let release: (value: DashboardStats) => void = () => {};
    const fetchStats = vi.fn(() => new Promise<DashboardStats>((resolve) => (release = resolve)));
    const onChange = vi.fn(async () => {});
    const loop = new RefreshLoop(fetchStats, onChange);
    const first = loop.tick();
    await loop.tick(); // busy: returns immediately
    release(stats("2026-01-01T10:00:00Z"));
    await first;
    expect(fetchStats).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledTimes(1);
  });
});
