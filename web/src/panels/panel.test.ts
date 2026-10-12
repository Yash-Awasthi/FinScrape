import { describe, expect, it } from "vite-plus/test";
import { Panel, type PanelConfig } from "./panel";

const base: PanelConfig = { id: "t", title: "T", w: 4, h: 3 };

describe("deterministic panel grid", () => {
  it("spans its declared width/height", () => {
    const p = new Panel(base);
    expect(p.el.style.gridColumn).toBe("span 4");
    expect(p.el.style.gridRow).toBe("span 3");
  });

  it("caps the span at the 12-column grid", () => {
    const p = new Panel({ id: "t2", title: "T2", w: 16, h: 2 });
    expect(p.el.style.gridColumn).toBe("span 12");
  });

  it("is layout-deterministic: same config, same placement", () => {
    const a = new Panel(base);
    const b = new Panel(base);
    expect(a.el.style.cssText).toBe(b.el.style.cssText);
  });
});
