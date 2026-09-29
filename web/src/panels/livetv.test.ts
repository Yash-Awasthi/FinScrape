import { describe, expect, it } from "vitest";

import { CHANNELS } from "../data/channels";
import { LiveTVPanel } from "./panels";

const painted = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

describe("LiveTVPanel", () => {
  it("mounts exactly one player, never one per channel", async () => {
    // Selecting "All countries" used to render an iframe for every channel in the
    // list, one live YouTube embed per channel, the most expensive thing the page
    // could do. The rail is buttons; only the stage is a frame.
    const panel = new LiveTVPanel();
    panel.render();
    await painted();
    expect(CHANNELS.length).toBeGreaterThan(1);
    expect(panel.body.querySelectorAll("iframe")).toHaveLength(1);
    expect(panel.body.querySelectorAll(".tv-pick").length).toBe(CHANNELS.length);
  });

  it("swaps the player when a channel is picked, without adding another", async () => {
    const panel = new LiveTVPanel();
    panel.render();
    await painted();
    const first = panel.body.querySelector("iframe")!.getAttribute("src");

    const other = [...panel.body.querySelectorAll<HTMLElement>(".tv-pick")].find(
      (b) => !b.classList.contains("active"),
    )!;
    other.click();
    await painted();

    const frames = panel.body.querySelectorAll("iframe");
    expect(frames).toHaveLength(1);
    expect(frames[0].getAttribute("src")).not.toBe(first);
  });

  it("narrows the rail by country without touching the player", async () => {
    const panel = new LiveTVPanel();
    panel.render();
    await painted();
    const playing = panel.body.querySelector("iframe")!.getAttribute("src");

    const select = panel.body.querySelector<HTMLSelectElement>(".tv-filter")!;
    select.value = "UK";
    select.dispatchEvent(new Event("change"));

    const shown = panel.body.querySelectorAll(".tv-pick").length;
    expect(shown).toBe(CHANNELS.filter((c) => c.country === "UK").length);
    expect(shown).toBeLessThan(CHANNELS.length);
    expect(panel.body.querySelector("iframe")!.getAttribute("src")).toBe(playing);
  });

  it("every channel embed is a youtube live URL", () => {
    for (const c of CHANNELS) {
      expect(c.channelId).toMatch(/^UC[\w-]{20,}$/);
    }
  });
});
