// Freshness bar: last ingest, the next expected one, and a stale warning.

import type { DashboardStats } from "../api";
import { timeAgo } from "../util";
import "./freshness.css";

const DEFAULT_INTERVAL = 15;
const STALE_FACTOR = 3;
const TICK_MS = 30_000;

function clockUTC(iso: string): string {
  const d = new Date(iso);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

export class Freshness {
  readonly el: HTMLElement;
  private stats: DashboardStats | null = null;
  private timer: number | null = null;

  constructor() {
    this.el = document.createElement("div");
    this.el.className = "freshness";
    this.el.setAttribute("role", "status");
    this.el.setAttribute("aria-live", "polite");
    // The age moves with the clock, not with new stats, so re-render on a tick.
    this.timer = window.setInterval(() => this.render(), TICK_MS);
  }

  update(stats: DashboardStats): void {
    this.stats = stats;
    this.render();
  }

  destroy(): void {
    if (this.timer !== null) window.clearInterval(this.timer);
    this.timer = null;
  }

  private render(): void {
    const stats = this.stats;
    if (!stats) return;
    const interval = stats.ingest_interval_minutes || DEFAULT_INTERVAL;
    if (!stats.last_update || Number.isNaN(Date.parse(stats.last_update))) {
      this.el.classList.remove("stale");
      this.el.textContent = "no ingest recorded yet";
      return;
    }
    const last = Date.parse(stats.last_update);
    const ageMinutes = Math.max(0, Math.round((Date.now() - last) / 60_000));
    const stale = ageMinutes > interval * STALE_FACTOR;
    this.el.classList.toggle("stale", stale);
    if (stale) {
      this.el.textContent = `stale: no ingest for ${ageMinutes}m, expected every ${interval}m`;
      return;
    }
    const next = new Date(last + interval * 60_000).toISOString();
    this.el.textContent =
      `last ingest ${clockUTC(stats.last_update)} UTC (${timeAgo(stats.last_update)} ago)` +
      ` - next expected by ${clockUTC(next)} UTC (worker runs every ${interval}m)`;
  }
}
