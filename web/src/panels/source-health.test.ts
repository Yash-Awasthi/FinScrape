import { describe, expect, it, vi } from "vitest";

import { api, type HealthResponse } from "../api";
import { timeAgo } from "../util";
import { SourceHealthPanel } from "./panels";

// setContent paints on the next animation frame.
const painted = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

const health = (sources: HealthResponse["sources"], db = true): HealthResponse => ({
  status: db ? "ok" : "degraded",
  db,
  llm: false,
  sources,
});

describe("timeAgo", () => {
  const now = Date.parse("2026-01-02T12:00:00Z");

  it("renders compact ages", () => {
    expect(timeAgo("2026-01-02T11:59:30Z", now)).toBe("30s");
    expect(timeAgo("2026-01-02T11:40:00Z", now)).toBe("20m");
    expect(timeAgo("2026-01-02T09:00:00Z", now)).toBe("3h");
    expect(timeAgo("2025-12-31T12:00:00Z", now)).toBe("2d");
  });

  it("never throws on missing or unparseable input", () => {
    expect(timeAgo(null, now)).toBe("never");
    expect(timeAgo("not a date", now)).toBe("never");
  });
});

describe("SourceHealthPanel", () => {
  it("keeps the last known statuses with a stale warning and retries", async () => {
    const request = vi.spyOn(api, "health")
      .mockResolvedValueOnce(health([{ source: "world/test", status: "STALE", fetched_at: "2026-01-01T00:00:00Z", record_count: 3 }]))
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(health([{ source: "world/test", status: "OK", fetched_at: new Date().toISOString(), record_count: 4 }]));
    const panel = new SourceHealthPanel();
    await panel.load();
    await painted();
    await panel.load();
    await painted();
    expect(panel.body.textContent).toContain("world/test");
    expect(panel.body.textContent).toContain("last known");
    expect(panel.body.querySelector('[role="status"]')?.textContent).toContain("Health unavailable");
    panel.body.querySelector<HTMLButtonElement>("button")!.click();
    await painted();
    expect(request).toHaveBeenCalledTimes(3);
    expect(panel.body.textContent).not.toContain("Health unavailable");
    expect(panel.body.textContent).toContain("last fetch");
  });

  it("summarizes stale and failing sources without claiming everything is live", async () => {
    vi.spyOn(api, "health").mockResolvedValue(health([
      { source: "late", status: "STALE", fetched_at: null, record_count: 1 },
      { source: "broken", status: "WARN", fetched_at: null, record_count: 0 },
    ]));
    const panel = new SourceHealthPanel();
    await panel.load();
    await painted();
    expect(panel.body.querySelector('[role="status"]')?.textContent).toContain("2 sources need attention");
  });

  it("surfaces a failing source above healthy ones", async () => {
    vi.spyOn(api, "health").mockResolvedValue(
      health([
        { source: "world_rss", status: "OK", fetched_at: null, record_count: 12 },
        { source: "gdelt", status: "WARN", fetched_at: null, record_count: 0 },
        { source: "usgs_quakes", status: "STALE", fetched_at: null, record_count: 3 },
      ]),
    );
    const panel = new SourceHealthPanel();
    await panel.load();
    await painted();

    const names = [...panel.body.querySelectorAll("b")].map((b) => b.textContent);
    expect(names).toEqual(["gdelt", "usgs_quakes", "world_rss"]); // worst first
    expect(panel.body.querySelector(".src-dot.bad")).not.toBeNull();
    expect(panel.body.textContent).toContain("failing");
  });

  it("reports an unreachable database as its own row", async () => {
    vi.spyOn(api, "health").mockResolvedValue(health([], false));
    const panel = new SourceHealthPanel();
    await panel.load();
    await painted();
    expect(panel.body.textContent).toContain("unreachable");
  });

  it("degrades to a message instead of throwing when the endpoint is down", async () => {
    vi.spyOn(api, "health").mockRejectedValue(new Error("502"));
    const panel = new SourceHealthPanel();
    await panel.load();
    await painted();
    expect(panel.body.textContent).toContain("Health unavailable");
  });
});
