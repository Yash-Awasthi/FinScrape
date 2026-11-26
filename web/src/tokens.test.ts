import { describe, expect, it } from "vite-plus/test";
import { readFileSync } from "node:fs";

const tokensCss = readFileSync("src/tokens.css", "utf8");
const stylesCss = readFileSync("src/styles.css", "utf8");

// Declarations in file order, so the numeric token scales are checked as authored.
function declarations(css: string): Array<[string, string]> {
  const block = css.match(/:root\s*\{([\s\S]*?)\}/)?.[1] ?? "";
  return [...block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map(
    (match) => [match[1], match[2].trim()] as [string, string],
  );
}

const tokens = new Map(declarations(tokensCss));
const hex = /^#(?:[0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i;

function valuesMatching(prefix: string): string[] {
  return [...tokens].filter(([name]) => name.startsWith(prefix)).map(([, value]) => value);
}

describe("design tokens", () => {
  it("scales spacing 4 to 48", () => {
    expect(valuesMatching("--space-")).toEqual([
      "4px",
      "8px",
      "12px",
      "16px",
      "24px",
      "32px",
      "48px",
    ]);
  });

  it("scales type 12 to 32", () => {
    expect(valuesMatching("--font-")).toEqual(["12px", "14px", "16px", "20px", "24px", "32px"]);
  });

  it("defines the radius and elevation steps", () => {
    for (const name of ["--radius-sm", "--radius-md", "--radius-lg", "--radius-pill"]) {
      expect(tokens.get(name), name).toBeTruthy();
    }
    for (const name of ["--elev-1", "--elev-2", "--elev-3"]) {
      expect(tokens.get(name), name).toBeTruthy();
    }
  });

  it("defines semantic colours as hex", () => {
    const names = [
      "--bg",
      "--panel",
      "--text",
      "--text-strong",
      "--muted",
      "--accent",
      "--up",
      "--down",
      "--warn",
    ];
    for (const name of names) {
      const value = tokens.get(name);
      expect(value, name).toBeDefined();
      expect(value, name).toMatch(hex);
    }
  });

  it("keeps the chart palette distinct from the semantic colours", () => {
    const chart = [1, 2, 3, 4, 5, 6, 7].map((step) => tokens.get(`--chart-${step}`));
    expect(chart.filter((value) => typeof value === "string")).toHaveLength(7);
    for (const value of chart) {
      expect(value ?? "").toMatch(hex);
    }
    expect(new Set(chart).size).toBe(7);

    const semantic = new Set(
      [
        "--bg",
        "--panel",
        "--text",
        "--text-strong",
        "--muted",
        "--accent",
        "--up",
        "--down",
        "--warn",
      ].map((name) => tokens.get(name)?.toLowerCase()),
    );
    for (const value of chart) {
      expect(semantic.has((value ?? "").toLowerCase())).toBe(false);
    }
  });
});

describe("styles.css", () => {
  it("imports the tokens first", () => {
    expect(stylesCss.startsWith('@import "./tokens.css";')).toBe(true);
  });

  it("no longer declares its own custom properties", () => {
    expect(stylesCss).not.toMatch(/--bg\s*:/);
  });
});
