// The four states every surface owes the reader: loading, empty, error, offline.
// They are one place so a panel cannot invent its own wording, and so the retry
// contract (keep the last good data, add a strip above it) is the same everywhere.

/** A skeleton shaped like the rows that will replace it, not a spinner. */
export function skeleton(rows = 3): string {
  const lines = Array.from(
    { length: rows },
    (_, i) => `<span class="skeleton-row" style="width:${100 - i * 12}%"></span>`,
  ).join("");
  return (
    `<div class="skeleton" data-state="loading" role="status" aria-busy="true" aria-label="Loading">` +
    `${lines}</div>`
  );
}

/** What the absence means and what the reader can do about it. */
export function emptyNotice(what: string, action: string): string {
  return (
    `<p class="empty state-empty" data-state="empty">${what} ` +
    `<span class="muted">${action}</span></p>`
  );
}

/**
 * An error strip with a retry button. Callers keep the last good content and put
 * this above it, so a failed refresh never blanks a populated panel.
 */
export function errorNotice(message: string, retry?: () => void, id = "retry"): HTMLElement {
  const strip = document.createElement("div");
  strip.className = "state-error";
  strip.dataset.state = "error";
  strip.setAttribute("role", "alert");
  const text = document.createElement("span");
  text.textContent = message;
  strip.append(text);
  if (retry) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "state-retry";
    button.id = id;
    button.textContent = "Retry";
    button.addEventListener("click", retry);
    strip.append(button);
  }
  return strip;
}

/** Shown app-wide when the socket drops; the last good data stays on screen. */
export function offlineNotice(): HTMLElement {
  const strip = document.createElement("div");
  strip.className = "state-offline";
  strip.dataset.state = "offline";
  strip.setAttribute("role", "status");
  strip.textContent = "Offline - reconnecting. Showing the last data that arrived.";
  return strip;
}
