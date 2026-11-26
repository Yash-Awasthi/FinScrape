import { expect, it, vi } from "vite-plus/test";

import {
  LIMIT,
  mountNotifications,
  newestFirst,
  renderNotifications,
  unreadCount,
  type AlertNotification,
  type NotificationsApi,
} from "./notifications";

function row(id: number, overrides: Partial<AlertNotification> = {}): AlertNotification {
  return {
    id,
    rule_id: "r1",
    rule_name: "Energy shock",
    event_id: 100 + id,
    event_subject: `Story ${id}`,
    event_verdict: "INVEST",
    event_timestamp: `2026-11-2${id % 10}T00:00:00Z`,
    action_type: "log",
    status: "sent",
    fired_at: `2026-11-26T0${id % 10}:00:00Z`,
    read: false,
    ...overrides,
  };
}

function feed(rows: AlertNotification[]): { notifications: AlertNotification[] } {
  return { notifications: rows };
}

it("sorts newest first and caps the feed at 50", () => {
  const rows = Array.from({ length: 60 }, (_, i) => row(i + 1));
  const out = newestFirst(rows);
  expect(out).toHaveLength(LIMIT);
  for (let i = 1; i < out.length; i += 1) {
    expect(out[i - 1].fired_at >= out[i].fired_at).toBe(true);
  }
});

it("counts unread rows", () => {
  expect(unreadCount([row(1), row(2, { read: true })])).toBe(1);
});

it("renders one row per alert with the event link, verdict and read toggle", () => {
  const host = renderNotifications(feed([row(2), row(1, { read: true })]));
  const rows = host.querySelectorAll("li.sug-row");
  expect(rows).toHaveLength(2);
  // Newest first: id 2 fires at 02:00, id 1 at 01:00.
  expect((rows[0] as HTMLElement).dataset.id).toBe("2");
  expect(host.querySelector("#notifications-unread")?.textContent).toBe("1 unread of 2");
  const link = rows[0].querySelector("a.ev-link") as HTMLAnchorElement;
  expect(link.getAttribute("href")).toBe("/app/event/102");
  expect(link.textContent).toBe("Story 2");
  expect(rows[0].querySelector(".verdict-badge")?.textContent).toBe("INVEST");
  // Unread row offers "mark as read"; the read row offers the reverse.
  expect(rows[0].querySelector("[data-action='toggle-read']")?.getAttribute("aria-label")).toBe(
    "Mark alert as read",
  );
  expect(rows[1].querySelector("[data-action='toggle-read']")?.getAttribute("aria-label")).toBe(
    "Mark alert as unread",
  );
  // The toggle is an inline SVG with an accessible label, never a bare glyph.
  expect(rows[0].querySelector("button svg")).not.toBeNull();
});

it("keeps the event reference without a link when the event id is missing", () => {
  const host = renderNotifications(feed([row(1, { event_id: null })]));
  expect(host.querySelector("a.ev-link")).toBeNull();
  expect(host.querySelector("span.ev-link")?.textContent).toBe("Story 1");
});

it("shows an honest empty state", () => {
  const host = renderNotifications(feed([]));
  expect(host.querySelector(".empty")?.textContent).toContain("No alerts have fired");
  expect(host.querySelector("li.sug-row")).toBeNull();
});

it("PATCHes the read mark and keeps the row state after reload", async () => {
  const stored = [row(1)];
  const list = vi.fn(async () => feed(stored.map((r) => ({ ...r }))));
  const setRead = vi.fn(async (id: number, read: boolean) => {
    const hit = stored.find((r) => r.id === id);
    if (hit) hit.read = read;
    return { ok: true };
  });
  const api: NotificationsApi = { list, setRead };
  const root = document.createElement("div");
  const view = mountNotifications(root, api);
  await view.reload();
  expect(root.querySelector("#notifications-unread")?.textContent).toBe("1 unread of 1");

  (root.querySelector("[data-action='toggle-read']") as HTMLButtonElement).click();
  await Promise.resolve();
  await Promise.resolve();
  expect(setRead).toHaveBeenCalledWith(1, true);
  expect(root.querySelector("[data-action='toggle-read']")?.getAttribute("aria-label")).toBe(
    "Mark alert as unread",
  );
  expect(root.querySelector("#notifications-unread")?.textContent).toBe("0 unread of 1");

  await view.reload();
  expect(root.querySelector<HTMLElement>("li.sug-row")?.dataset.read).toBe("true");
  expect(list).toHaveBeenCalledWith(LIMIT);
});

it("rolls the mark back and explains when the PATCH fails", async () => {
  const api: NotificationsApi = {
    list: vi.fn(async () => feed([row(1)])),
    setRead: vi.fn(async () => {
      throw new Error("PATCH /api/alerts/notifications/1 -> 401");
    }),
  };
  const root = document.createElement("div");
  const view = mountNotifications(root, api);
  await view.reload();
  (root.querySelector("[data-action='toggle-read']") as HTMLButtonElement).click();
  await Promise.resolve();
  await Promise.resolve();
  expect(root.querySelector<HTMLElement>("li.sug-row")?.dataset.read).toBe("false");
  expect(root.querySelector(".warn")?.textContent).toContain("401");
});
