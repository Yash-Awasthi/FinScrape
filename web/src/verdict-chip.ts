import { verdictColor } from "./api";
import { escapeHtml } from "./util";

const DEFINITION: Record<string, string> = {
  INVEST: "score +3 or higher, the story is expected to lift its tickers",
  PULL_OUT: "score -3 or lower, the story is expected to drag its tickers down",
  OBSERVE: "score 0 to +2, no directional call",
  CAUTIOUS: "score -1 or -2, no directional call, leaning down",
};

export const VERDICT_WINDOW = "next-day raw move, then +2 and +4 trading days vs SPY";

export function verdictTitle(verdict: string): string {
  return `${verdict}: ${DEFINITION[verdict] ?? "unrecognised call"}. Scoring window: ${VERDICT_WINDOW}.`;
}

export function verdictChip(verdict: string): string {
  return `<span class="verdict-chip" tabindex="0" title="${escapeHtml(verdictTitle(verdict))}"><span class="dot" style="background:${verdictColor(verdict)}"></span>${escapeHtml(verdict)}</span>`;
}
