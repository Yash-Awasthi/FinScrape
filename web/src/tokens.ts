// Colour and dimension values live in tokens.css; everything else references them.
// cssVar builds the reference, resolveColor turns it into a concrete colour where a
// canvas/WebGL API cannot read CSS custom properties.

export function cssVar(name: string): string {
  return `var(${name})`;
}

/** Resolve a token or a var(...) string to a concrete colour for WebGL/canvas. */
export function resolveColor(value: string): string {
  const name =
    /^var\(\s*(--[\w-]+)\s*\)$/.exec(value)?.[1] ?? (value.startsWith("--") ? value : "");
  if (!name) return value;
  if (typeof document === "undefined") return "currentColor";
  const resolved = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return resolved || "currentColor";
}
