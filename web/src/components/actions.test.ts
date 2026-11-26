import { afterEach, describe, expect, it } from "vite-plus/test";

import { Shell } from "../app/shell";
import { actionBar } from "./actions";

afterEach(() => {
  document.body.replaceChildren();
});

function threeSecondaries() {
  const calls = { primary: 0, one: 0, two: 0, three: 0 };
  const bar = actionBar({
    primary: {
      label: "\u21bb",
      title: "Refresh feed and panels",
      className: "refresh",
      run: () => {
        calls.primary++;
      },
    },
    secondary: [
      { label: "One", run: () => void calls.one++ },
      { label: "Two", run: () => void calls.two++ },
      { label: "Three", run: () => void calls.three++ },
    ],
  });
  document.body.append(bar);
  return { bar, calls };
}

describe("actionBar", () => {
  it("shows exactly one primary button with its marker and extra class", () => {
    const { bar } = threeSecondaries();
    const primaries = bar.querySelectorAll(".btn-primary");
    expect(primaries.length).toBe(1);
    const primary = primaries[0] as HTMLButtonElement;
    expect(primary.dataset.primary).toBe("true");
    expect(primary.classList.contains("refresh")).toBe(true);
  });

  it("puts every secondary inside the overflow details, behind a labelled summary", () => {
    const { bar } = threeSecondaries();
    const menu = bar.querySelector("details.action-overflow");
    expect(menu).not.toBeNull();
    const secondaries = bar.querySelectorAll(".action-secondary");
    expect(secondaries.length).toBe(3);
    for (const secondary of secondaries) {
      expect(menu!.contains(secondary)).toBe(true);
    }
    expect(menu!.querySelector("summary")!.getAttribute("aria-label")).toBe("More actions");
  });

  it("runs a secondary once and closes the menu", () => {
    const { bar, calls } = threeSecondaries();
    const menu = bar.querySelector("details.action-overflow") as HTMLDetailsElement;
    menu.open = true;
    const second = menu.querySelectorAll<HTMLButtonElement>(".action-secondary")[1];
    second.click();
    expect(calls.two).toBe(1);
    expect(calls.one).toBe(0);
    expect(menu.open).toBe(false);
  });

  it("closes an open menu on Esc inside the bar", () => {
    const { bar } = threeSecondaries();
    const menu = bar.querySelector("details.action-overflow") as HTMLDetailsElement;
    menu.open = true;
    bar.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(menu.open).toBe(false);
  });

  it("closes an open menu on a document click outside the details", () => {
    const { bar } = threeSecondaries();
    const menu = bar.querySelector("details.action-overflow") as HTMLDetailsElement;
    menu.open = true;
    document.body.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(menu.open).toBe(false);
  });

  it("runs the primary callback once on click", () => {
    const { bar, calls } = threeSecondaries();
    (bar.querySelector(".btn-primary") as HTMLButtonElement).click();
    expect(calls.primary).toBe(1);
  });
});

describe("Shell header actions", () => {
  it("keeps one primary action, the refresh control, across views", () => {
    const shell = new Shell(
      () => {},
      [
        { id: "feed", label: "Feed" },
        { id: "desk", label: "Desk" },
      ],
      () => {},
    );
    expect(shell.root.querySelectorAll(".btn-primary").length).toBe(1);
    const refresh = shell.root.querySelector(".btn-primary") as HTMLButtonElement;
    expect(refresh.getAttribute("aria-label")).toBe("Refresh feed and panels");
    expect(refresh.classList.contains("refresh")).toBe(true);

    shell.setView("desk");
    expect(shell.root.querySelectorAll(".btn-primary").length).toBe(1);
  });
});
