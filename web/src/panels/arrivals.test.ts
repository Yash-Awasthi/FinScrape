import { afterEach, describe, expect, it, vi } from "vite-plus/test";

import { Panel } from "./panel";

// setContent paints on the next animation frame.
const painted = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

function feed(id = "feed"): Panel {
  return new Panel({ id, title: id, w: 5, h: 9 });
}

function rows(...ids: number[]): string {
  return (
    "<table><tbody>" +
    ids.map((id) => `<tr data-event-id="${id}"><td>${id}</td></tr>`).join("") +
    "</tbody></table>"
  );
}

afterEach(() => {
  delete (window as { matchMedia?: unknown }).matchMedia;
});

describe("feed arrival marks", () => {
  it("marks nothing on the first render", async () => {
    const p = feed();
    p.setContent(rows(1, 2));
    await painted();
    expect(p.body.querySelectorAll(".row-new")).toHaveLength(0);
  });

  it("marks only the row that arrived since the previous render", async () => {
    const p = feed();
    p.setContent(rows(1, 2));
    await painted();
    p.setContent(rows(1, 2, 3));
    await painted();
    const marked = p.body.querySelectorAll(".row-new");
    expect(marked).toHaveLength(1);
    expect((marked[0] as HTMLElement).dataset.eventId).toBe("3");
  });

  it("marks nothing under reduced motion", async () => {
    window.matchMedia = vi.fn((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;

    const p = feed();
    p.setContent(rows(1, 2));
    await painted();
    p.setContent(rows(1, 2, 3));
    await painted();
    expect(p.body.querySelectorAll(".row-new")).toHaveLength(0);
  });

  it("does not mark arrivals on a panel that is not the feed", async () => {
    const p = feed("desk");
    p.setContent(rows(1, 2));
    await painted();
    p.setContent(rows(1, 2, 3));
    await painted();
    expect(p.body.querySelectorAll(".row-new")).toHaveLength(0);
  });
});
