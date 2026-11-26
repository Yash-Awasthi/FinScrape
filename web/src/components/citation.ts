// Citation links: every claim shown in the UI carries one, resolving to its evidence.

import { escapeHtml, sourceLabel } from "../util";
import "./citation.css";

export interface CitableEvent {
  id: number;
  sources?: string[];
  articles?: string[];
}

/** The article URL only when it is a real http(s) URL: this is the XSS boundary. */
export function safeArticle(url: unknown): string | null {
  if (typeof url !== "string" || !url) return null;
  try {
    const parsed = new URL(url);
    // javascript:/data: anchors execute; only web protocols may leave the app.
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? url : null;
  } catch {
    return null;
  }
}

export function eventHref(id: number): string {
  return `/app/event/${id}`;
}

export function scenarioHref(id: string): string {
  return `/app/scenario/${encodeURIComponent(id)}`;
}

/** One anchor next to a claim: the first article, else the event evidence page. */
export function citeLink(ev: CitableEvent, what = "claim"): string {
  const article = safeArticle(ev.articles?.[0]);
  const href = article ?? eventHref(ev.id);
  const sources = (ev.sources ?? []).filter(Boolean);
  const n = ev.articles?.length ?? 0;
  const count = `${n} article${n === 1 ? "" : "s"}`;
  const text = sources.length
    ? `source: ${escapeHtml(sourceLabel(sources[0]))} &middot; ${count}`
    : `source: not recorded &middot; ${count}`;
  const labels = sources.length ? sources.map(sourceLabel).join(", ") : "source not recorded";
  const title = article
    ? `${what} - ${labels}`
    : `${what} - ${labels} - open the event evidence page`;
  const outside = article ? ' target="_blank" rel="noopener noreferrer"' : "";
  return (
    `<a class="cite" href="${escapeHtml(href)}"${outside} title="${escapeHtml(title)}">` +
    `${text}</a>`
  );
}

export function claimWithCite(text: string, ev: CitableEvent): string {
  return `${escapeHtml(text)} ${citeLink(ev)}`;
}
