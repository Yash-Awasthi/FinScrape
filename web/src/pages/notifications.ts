// Notification centre (plan m4.3.1): the last 50 things the alert rules fired, with a
// read/unread mark per row and the event each one points at. Reads need no API key;
// the read mark is a PATCH and does need one (stored in My Desk).

import { API_BASE, getJSON } from "../api";
import { apiKey } from "../watchlist";

export interface AlertNotification {
  id: number;
  rule_id: string | null;
  rule_name: string | null;
  event_id: number | null;
  event_subject: string | null;
  event_verdict: string | null;
  event_timestamp: string | null;
  action_type: string;
  status: string;
  fired_at: string;
  read: boolean;
}

export interface NotificationsFeed {
  notifications: AlertNotification[];
  unread?: number;
}

/** The narrow surface the view needs, so a test can pass a fake. */
export interface NotificationsApi {
  list(limit: number): Promise<NotificationsFeed>;
  setRead(id: number, read: boolean): Promise<unknown>;
}

export const LIMIT = 50;

export const notificationsApi: NotificationsApi = {
  list: (limit) => getJSON<NotificationsFeed>(`/api/alerts/notifications?limit=${limit}`),
  async setRead(id, read) {
    const key = apiKey();
    if (!key) throw new Error("no API key: add it in My Desk to mark alerts read");
    const res = await fetch(`${API_BASE}/api/alerts/notifications/${id}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": key,
        Accept: "application/json",
      },
      body: JSON.stringify({ read }),
    });
    if (!res.ok) throw new Error(`PATCH /api/alerts/notifications/${id} -> ${res.status}`);
    return res.json();
  },
};

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  cls?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

/** Newest first, as the API returns them; the limit is enforced again here. */
export function newestFirst(rows: AlertNotification[]): AlertNotification[] {
  return [...rows]
    .sort((a, b) => (b.fired_at > a.fired_at ? 1 : b.fired_at < a.fired_at ? -1 : b.id - a.id))
    .slice(0, LIMIT);
}

export function unreadCount(rows: AlertNotification[]): number {
  return rows.reduce((n, r) => n + (r.read ? 0 : 1), 0);
}

function toggleSvg(read: boolean): SVGSVGElement {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("width", "14");
  svg.setAttribute("height", "14");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("fill", "currentColor");
  // An open circle for unread, a ticked circle for read: the same shape, one extra mark.
  path.setAttribute(
    "d",
    read
      ? "M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1Zm3.5 5.2-4.2 4.3-2.8-2.7 1.1-1.1 1.7 1.6 3.1-3.2 1.1 1.1Z"
      : "M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1Zm0 1.4a5.6 5.6 0 1 1 0 11.2A5.6 5.6 0 0 1 8 2.4Z",
  );
  svg.append(path);
  return svg;
}

function verdictBadge(verdict: string | null): HTMLElement {
  return el("span", "verdict-badge", verdict ?? "unscored");
}

export function renderNotifications(feed: NotificationsFeed): HTMLElement {
  const host = el("section", "ev-host");
  const rows = newestFirst(feed.notifications ?? []);
  const head = el("div", "sub-head", "Notifications");
  const count = el("p", "muted");
  count.id = "notifications-unread";
  count.textContent = `${feed.unread ?? unreadCount(rows)} unread of ${rows.length}`;
  host.append(head, count);
  if (!rows.length) {
    host.append(el("p", "empty", "No alerts have fired yet."));
    return host;
  }
  const list = el("ul", "sug-list");
  for (const row of rows) {
    const li = el("li", "sug-row");
    li.dataset.id = String(row.id);
    li.dataset.read = row.read ? "true" : "false";

    const toggle = el("button", "ai-btn");
    toggle.type = "button";
    toggle.dataset.action = "toggle-read";
    toggle.setAttribute("aria-label", row.read ? "Mark alert as unread" : "Mark alert as read");
    toggle.append(toggleSvg(row.read));

    const link =
      row.event_id !== null
        ? el("a", "ev-link", row.event_subject ?? `event ${row.event_id}`)
        : el("span", "ev-link", row.event_subject ?? "event not recorded");
    if (row.event_id !== null) link.setAttribute("href", `/app/event/${row.event_id}`);

    const meta = el(
      "span",
      "row-meta",
      `${row.rule_name ?? "rule"} . ${row.action_type} . ${row.status}`,
    );
    li.append(toggle, link, verdictBadge(row.event_verdict), meta);
    const when = el("time", "muted", row.fired_at);
    when.dateTime = row.fired_at;
    li.append(when);
    list.append(li);
  }
  host.append(list);
  return host;
}

/**
 * Mount the feed into `root`. The toggle updates the row optimistically and rolls the
 * mark back if the PATCH fails, so a reload agrees with what the screen showed.
 */
export function mountNotifications(
  root: HTMLElement,
  api: NotificationsApi = notificationsApi,
): { reload: () => Promise<void>; destroy: () => void } {
  let current: NotificationsFeed = { notifications: [] };
  let alive = true;

  function paint(): void {
    root.replaceChildren(renderNotifications(current));
  }

  async function reload(): Promise<void> {
    current = await api.list(LIMIT);
    if (alive) paint();
  }

  async function onClick(event: Event): Promise<void> {
    const button = (event.target as HTMLElement | null)?.closest<HTMLButtonElement>(
      "button[data-action='toggle-read']",
    );
    const li = button?.closest<HTMLElement>("li.sug-row");
    if (!button || !li) return;
    const id = Number(li.dataset.id);
    const row = current.notifications.find((r) => r.id === id);
    if (!row) return;
    const next = !row.read;
    row.read = next;
    paint();
    try {
      await api.setRead(id, next);
    } catch (err) {
      row.read = !next;
      paint();
      const status = el("p", "warn", (err as Error).message);
      root.append(status);
    }
  }

  const handler = (e: Event): void => void onClick(e);
  root.addEventListener("click", handler);
  return {
    reload,
    destroy: () => {
      alive = false;
      root.removeEventListener("click", handler);
    },
  };
}

/** Route view, so main.ts can mount the centre on a real path. */
export class NotificationsPageView {
  readonly el: HTMLElement;
  private readonly mounted: ReturnType<typeof mountNotifications>;

  constructor(api: NotificationsApi = notificationsApi) {
    this.el = el("div", "ev-host");
    this.el.hidden = true;
    this.mounted = mountNotifications(this.el, api);
  }

  async load(): Promise<void> {
    this.el.hidden = false;
    await this.mounted.reload();
  }

  hide(): void {
    this.el.hidden = true;
  }
}
