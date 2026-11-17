// Polls the cheap stats endpoint and reloads the feed when the API has newer writes.
//
// Production runs the worker as a GitHub Action writing to Supabase, with no Redis,
// so `new_events` frames never reach the dashboard: without this the feed only moves
// when someone presses refresh. The poll reads stats (two small aggregates) and only
// pays for the event/correlation payloads when `last_update` actually moved.

import type { DashboardStats } from "./api";

export class RefreshLoop {
  private timer: ReturnType<typeof setInterval> | null = null;
  private stamp: string | null = null;
  private busy = false;

  constructor(
    private readonly fetchStats: () => Promise<DashboardStats>,
    private readonly onChange: (stats: DashboardStats) => Promise<void>,
    private readonly intervalMs = 60_000,
    private readonly visible: () => boolean = () => document.visibilityState !== "hidden",
  ) {}

  /** Seed the last-seen write stamp (initial load or a WS frame). */
  note(stats: DashboardStats | null | undefined): void {
    if (stats?.last_update) this.stamp = stats.last_update;
  }

  start(): void {
    this.stop();
    this.timer = setInterval(() => void this.tick(), this.intervalMs);
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  /** One poll. Public so a visible tab can poll immediately on focus. */
  async tick(): Promise<void> {
    if (this.busy || !this.visible()) return;
    this.busy = true;
    try {
      const stats = await this.fetchStats();
      const next = stats.last_update;
      if (!next || next === this.stamp) return;
      await this.onChange(stats);
      // Only now: a failed reload is retried on the next tick, not silently dropped.
      this.stamp = next;
    } catch {
      // API asleep or offline — the WS client reconnects and the next tick retries.
    } finally {
      this.busy = false;
    }
  }
}
