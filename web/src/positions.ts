// Optional manual positions (plan m4.1.3): symbol, quantity, cost basis.
// Browser-local only: no server round trip, no quote feed, no advice.

export interface Position {
  symbol: string;
  quantity: number;
  cost_basis: number;
}

const STORAGE = "worldfin.positions";

function clean(row: unknown): Position | null {
  if (!row || typeof row !== "object") return null;
  const raw = row as Record<string, unknown>;
  const symbol = typeof raw.symbol === "string" ? raw.symbol.trim().toUpperCase() : "";
  const quantity = Number(raw.quantity);
  const costBasis = Number(raw.cost_basis);
  if (!symbol || !Number.isFinite(quantity) || !Number.isFinite(costBasis)) return null;
  return { symbol, quantity, cost_basis: costBasis };
}

/** Reads never throw: a corrupted or blocked store reads as no positions. */
export function positions(): Position[] {
  try {
    const raw = localStorage.getItem(STORAGE);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed.map(clean).filter((p): p is Position => p !== null);
  } catch {
    return [];
  }
}

function save(rows: Position[]): void {
  try {
    localStorage.setItem(STORAGE, JSON.stringify(rows));
  } catch {
    // A private-mode store that refuses the write still leaves the session usable.
  }
  window.dispatchEvent(new CustomEvent("worldfin:positions", { detail: rows }));
}

/** A symbol already held is replaced, not duplicated. */
export function addPosition(symbol: string, quantity: number, costBasis: number): Position[] {
  const next = clean({ symbol, quantity, cost_basis: costBasis });
  if (!next) return positions();
  const rows = positions().filter((p) => p.symbol !== next.symbol);
  rows.push(next);
  rows.sort((a, b) => a.symbol.localeCompare(b.symbol));
  save(rows);
  return rows;
}

export function removePosition(symbol: string): Position[] {
  const rows = positions().filter((p) => p.symbol !== symbol.trim().toUpperCase());
  save(rows);
  return rows;
}
