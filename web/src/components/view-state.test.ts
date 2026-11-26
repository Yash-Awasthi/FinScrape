import { describe, expect, it, vi } from "vite-plus/test";
import { emptyNotice, errorNotice, offlineNotice, skeleton } from "./view-state";
import { Panel } from "../panels/panel";

function mount(html: string): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = html;
  return host;
}

describe("skeleton", () => {
  it("shapes the loading state like the rows that will replace it", () => {
    const host = mount(skeleton(3));
    expect(host.querySelector('[data-state="loading"]')).not.toBeNull();
    const rows = host.querySelectorAll<HTMLElement>(".skeleton-row");
    expect(rows.length).toBe(3);
    expect(Array.from(rows).map((r) => r.style.width)).toEqual(["100%", "88%", "76%"]);
    expect(host.querySelector(".skeleton")?.getAttribute("aria-busy")).toBe("true");
  });
});

describe("emptyNotice", () => {
  it("says what is absent and what the reader can do", () => {
    const host = mount(emptyNotice("no calls", "run a scan"));
    const notice = host.querySelector('[data-state="empty"]');
    expect(notice?.textContent).toContain("no calls");
    expect(notice?.textContent).toContain("run a scan");
  });
});

describe("errorNotice", () => {
  it("is an alert with no button when there is nothing to retry", () => {
    const strip = errorNotice("boom");
    expect(strip.getAttribute("role")).toBe("alert");
    expect(strip.dataset.state).toBe("error");
    expect(strip.querySelector("button")).toBeNull();
  });

  it("retries exactly once per click", () => {
    const fn = vi.fn();
    const strip = errorNotice("boom", fn);
    const button = strip.querySelector("button");
    expect(button?.textContent).toBe("Retry");
    button?.click();
    expect(fn).toHaveBeenCalledTimes(1);
  });
});

describe("offlineNotice", () => {
  it("keeps the reader oriented when the socket drops", () => {
    const strip = offlineNotice();
    expect(strip.dataset.state).toBe("offline");
    expect(strip.textContent).toContain("last data");
  });
});

describe("panel states", () => {
  it("starts as a skeleton", () => {
    const panel = new Panel({ id: "t", title: "T", w: 4, h: 3 });
    expect(panel.body.firstElementChild?.classList.contains("skeleton")).toBe(true);
  });

  it("keeps one error strip no matter how many failures land", () => {
    const fn = vi.fn();
    const panel = new Panel({ id: "t", title: "T", w: 4, h: 3 });
    panel.showError("nope", fn);
    panel.showError("again", fn);
    const strips = panel.body.querySelectorAll(".state-error");
    expect(strips.length).toBe(1);
    expect(strips[0].textContent).toContain("again");
  });

  it("clears the strip after a good load", () => {
    const panel = new Panel({ id: "t", title: "T", w: 4, h: 3 });
    panel.showError("nope");
    panel.clearError();
    expect(panel.body.querySelector(".state-error")).toBeNull();
  });
});
