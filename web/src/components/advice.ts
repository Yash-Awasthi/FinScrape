// The advice line for surfaces where a user acts: follows, watchlists, positions.

import { escapeHtml } from "../util";

export const NOT_ADVICE = "Not financial advice.";

/** One disclaimer paragraph, optionally carrying the surface's own caveat. */
export function adviceNote(detail?: string): string {
  return `<p class="disclaimer">${NOT_ADVICE}${detail ? " " + escapeHtml(detail) : ""}</p>`;
}
