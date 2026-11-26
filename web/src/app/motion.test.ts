import { afterEach, describe, expect, it, vi } from "vite-plus/test";

import { animateViewChange, newArrivalIds, reducedMotion, VIEW_CHANGE_MS } from "./motion";
import { Shell } from "./shell";

function mockMotion(matches: boolean): void {
  window.matchMedia = vi.fn((query: string) => ({
    matches,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

afterEach(() => {
  delete (window as { matchMedia?: unknown }).matchMedia;
});

describe("reducedMotion", () => {
  it("is true when the media query matches", () => {
    mockMotion(true);
    expect(reducedMotion()).toBe(true);
  });

  it("is false when the media query does not match", () => {
    mockMotion(false);
    expect(reducedMotion()).toBe(false);
  });

  it("is false when matchMedia is unavailable", () => {
    mockMotion(true);
    delete (window as { matchMedia?: unknown }).matchMedia;
    expect(reducedMotion()).toBe(false);
  });
});

describe("newArrivalIds", () => {
  it("returns nothing on the first render", () => {
    expect(newArrivalIds([{ id: 1 }, { id: 2 }], new Set())).toEqual(new Set());
  });

  it("returns only ids missing from the seen set", () => {
    expect(newArrivalIds([{ id: 2 }, { id: 3 }], new Set([1, 2]))).toEqual(new Set([3]));
  });
});

describe("animateViewChange", () => {
  it("does not animate the first paint", () => {
    const animate = vi.fn();
    animateViewChange({ animate } as unknown as HTMLElement, null, "today");
    expect(animate).not.toHaveBeenCalled();
  });

  it("does not animate when the view is unchanged", () => {
    const animate = vi.fn();
    animateViewChange({ animate } as unknown as HTMLElement, "today", "today");
    expect(animate).not.toHaveBeenCalled();
  });

  it("does not animate under reduced motion", () => {
    mockMotion(true);
    const animate = vi.fn();
    animateViewChange({ animate } as unknown as HTMLElement, "today", "record");
    expect(animate).not.toHaveBeenCalled();
  });

  it("animates a view change for the view change duration", () => {
    const animate = vi.fn();
    animateViewChange({ animate } as unknown as HTMLElement, "today", "record");
    expect(animate).toHaveBeenCalledTimes(1);
    expect(animate).toHaveBeenCalledWith(expect.any(Array), {
      duration: VIEW_CHANGE_MS,
      easing: "ease-out",
    });
  });

  it("shell skips the first view and animates the next", () => {
    const shell = new Shell(
      () => {},
      [
        { id: "today", label: "Today" },
        { id: "record", label: "Record" },
      ],
      () => {},
    );
    const animate = vi.fn();
    shell.content.animate = animate;
    shell.setView("today");
    expect(animate).not.toHaveBeenCalled();
    shell.setView("record");
    expect(animate).toHaveBeenCalledTimes(1);
    expect(animate).toHaveBeenCalledWith(expect.any(Array), {
      duration: VIEW_CHANGE_MS,
      easing: "ease-out",
    });
  });
});
