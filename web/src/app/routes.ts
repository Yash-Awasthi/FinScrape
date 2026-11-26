// Path routes for the dashboard SPA. The dashboard itself is hash-switched (#today,
// #desk...); a *detail* page is a real path so it can be linked: /app/event/12.
// A hash form (#/app/event/12) is accepted too, for hosts without an SPA rewrite.

export type Route =
  | { kind: "event"; id: number }
  | { kind: "scenario"; id: string }
  | { kind: "alerts" }
  | null;

const EVENT = /^\/app\/event\/(\d+)\/?$/;
const SCENARIO = /^\/app\/scenario\/(s\d+)\/?$/;
const ALERTS = /^\/app\/alerts\/?$/;

export function parseRoute(pathname: string, hash = ""): Route {
  const path = hash.startsWith("#/") ? hash.slice(1) : pathname;
  const event = EVENT.exec(path);
  if (event) {
    const id = Number(event[1]);
    return Number.isSafeInteger(id) ? { kind: "event", id } : null;
  }
  const scenario = SCENARIO.exec(path);
  if (scenario) return { kind: "scenario", id: scenario[1] };
  if (ALERTS.test(path)) return { kind: "alerts" };
  return null;
}

/** The canonical dashboard link for a detail page's back button. */
export const DASHBOARD = "/app/#today";
