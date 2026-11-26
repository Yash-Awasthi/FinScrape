// Alerts page (plan t13): a readable builder over /api/alerts/rules. The engine
// matches a rule's conditions with AND logic, so this page only assembles that JSON.
// Reads need no key; saving, toggling and deleting do, and the key lives in My Desk.

import { API_BASE, getJSON } from "../api";
import { DASHBOARD } from "../app/routes";
import { apiKey } from "../watchlist";

export interface QuietHours {
  start: string;
  end: string;
}

export interface AlertCondition {
  field: string;
  operator: string;
  value: unknown;
}

export interface AlertActionOut {
  action_type: string;
  config?: Record<string, unknown>;
}

export interface AlertRuleOut {
  id: string;
  name: string;
  conditions: AlertCondition[];
  actions: AlertActionOut[];
  enabled: boolean;
  created_at?: string;
  quiet_hours?: QuietHours | Record<string, never>;
}

export interface FieldSpec {
  field: string;
  label: string;
  operators: string[];
  numeric?: boolean;
  hint: string;
}

export const FIELDS: FieldSpec[] = [
  { field: "verdict", label: "Verdict", operators: ["eq", "in"], hint: "INVEST" },
  { field: "sector", label: "Sector", operators: ["eq", "in"], hint: "energy" },
  { field: "tickers", label: "Ticker", operators: ["contains"], hint: "XOM" },
  { field: "topics", label: "Topic", operators: ["eq", "in"], hint: "shipping" },
  {
    field: "signal_score",
    label: "Score threshold",
    operators: ["gte"],
    numeric: true,
    hint: "4",
  },
  { field: "event_type", label: "Event type", operators: ["eq", "in"], hint: "earnings" },
];

export const OPERATOR_LABELS: Record<string, string> = {
  eq: "is",
  in: "is any of",
  contains: "contains",
  gte: "at least",
};

export interface Channel {
  id: string;
  label: string;
  disabled: boolean;
}

// Email and webhook are named so the next step is visible, but neither sends yet.
export const CHANNELS: Channel[] = [
  { id: "telegram", label: "Telegram", disabled: false },
  { id: "email", label: "Email (next)", disabled: true },
  { id: "webhook", label: "Webhook (next)", disabled: true },
];

const HHMM = /^([01][0-9]|2[0-3]):[0-5][0-9]$/;

export function fieldSpec(field: string): FieldSpec {
  const spec = FIELDS.find((f) => f.field === field);
  if (!spec) throw new Error(`Unknown condition field: ${field}`);
  return spec;
}

/**
 * One row from the form as the engine's condition JSON, or null when the row is
 * empty. A field/operator pair the engine would reject throws instead of being sent.
 */
export function conditionPayload(
  field: string,
  operator: string,
  raw: string,
): AlertCondition | null {
  const spec = fieldSpec(field);
  if (!spec.operators.includes(operator)) {
    throw new Error(`${spec.label} does not support "${operator}".`);
  }
  const text = raw.trim();
  if (!text) return null;
  if (operator === "in") {
    const list = text
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
    return list.length ? { field: spec.field, operator, value: list } : null;
  }
  if (spec.numeric) {
    const number = Number(text);
    if (!Number.isFinite(number)) throw new Error(`${spec.label} needs a number.`);
    return { field: spec.field, operator, value: number };
  }
  return { field: spec.field, operator, value: text };
}

function valueText(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "string" || typeof value === "number") return String(value);
  return value === null || value === undefined ? "" : JSON.stringify(value);
}

export function conditionText(condition: AlertCondition): string {
  const value = valueText(condition.value);
  return `${condition.field} ${OPERATOR_LABELS[condition.operator] ?? condition.operator} ${value}`;
}

/** Both blank means no quiet window; one blank or a bad clock is a mistake. */
export function quietHoursValue(start: string, end: string): QuietHours | null {
  const from = start.trim();
  const to = end.trim();
  if (!from && !to) return null;
  if (!from || !to) throw new Error("Quiet hours need both a start and an end.");
  if (!HHMM.test(from) || !HHMM.test(to)) {
    throw new Error("Quiet hours must be HH:MM in UTC.");
  }
  if (from === to) {
    throw new Error("Quiet hours start and end are the same; leave both blank for no window.");
  }
  return { start: from, end: to };
}

export function formatQuietHours(value: unknown): string {
  if (!value || typeof value !== "object") return "off";
  const { start, end } = value as Partial<QuietHours>;
  if (!start || !end) return "off";
  return start === end ? `${start}-${end} UTC (no window)` : `${start}-${end} UTC`;
}

export interface RulePayload {
  name: string;
  conditions: AlertCondition[];
  actions: AlertActionOut[];
  quiet_hours?: QuietHours;
}

export function rulePayload(
  name: string,
  conditions: AlertCondition[],
  channel = "telegram",
  quiet: QuietHours | null = null,
): RulePayload {
  const trimmed = name.trim();
  if (!trimmed) throw new Error("Name the rule first.");
  if (!conditions.length) throw new Error("Add at least one condition.");
  const payload: RulePayload = {
    name: trimmed,
    conditions,
    actions: [{ action_type: channel, config: {} }],
  };
  if (quiet) payload.quiet_hours = quiet;
  return payload;
}

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  cls?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** One form state, as the builder's own validation sees it (plan m4.3.3). */
export interface BuilderForm {
  name: string;
  conditions: Array<{ field: string; operator: string; value: string }>;
  channel?: string;
  quietStart?: string;
  quietEnd?: string;
}

/**
 * The POST /api/alerts/rules body for a whole form. Throws the sentence the form shows:
 * a missing name, no usable condition, a bad clock, or equal quiet-hours ends.
 */
export function buildRule(form: BuilderForm): RulePayload {
  const conditions = form.conditions
    .map((c) => conditionPayload(c.field, c.operator, c.value))
    .filter((c): c is AlertCondition => c !== null);
  const quiet = quietHoursValue(form.quietStart ?? "", form.quietEnd ?? "");
  return rulePayload(form.name, conditions, form.channel ?? "telegram", quiet);
}

function backLink(): HTMLAnchorElement {
  const back = el("a", "ev-back", "Back to the dashboard");
  back.href = DASHBOARD;
  return back;
}

function message(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

async function loadRules(): Promise<AlertRuleOut[]> {
  const body = await getJSON<{ rules: AlertRuleOut[] }>("/api/alerts/rules");
  return body.rules;
}

async function mutate<T>(method: string, path: string, body?: unknown): Promise<T> {
  const key = apiKey();
  if (!key) throw new Error("No API key. Add it in My Desk, then try again.");
  const res = await fetch(API_BASE + path, {
    method,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-API-Key": key,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 401) throw new Error("The API key was rejected.");
  if (!res.ok) throw new Error(`${method} ${path} failed (${res.status}).`);
  return res.json() as Promise<T>;
}

interface RuleHandlers {
  toggle: (rule: AlertRuleOut, enabled: boolean) => void;
  remove: (rule: AlertRuleOut) => void;
}

export function renderRulesList(rules: AlertRuleOut[], handlers: RuleHandlers): HTMLElement {
  const box = el("section", "ev-block");
  box.append(el("h2", "ev-block-title", "Saved rules"));
  if (!rules.length) {
    box.append(el("p", "empty", "No rule yet. The form below builds the first one."));
    return box;
  }
  const table = el("table", "grid-table");
  const head = el("tr");
  for (const label of ["Rule", "When", "Quiet hours", "On", ""]) {
    head.append(el("th", "", label));
  }
  const thead = el("thead");
  thead.append(head);
  table.append(thead);
  const body = el("tbody");
  for (const rule of rules) {
    const row = el("tr");
    const name = el("td", "subj-cell", rule.name);
    const when = el("td", "", rule.conditions.map(conditionText).join(" and "));
    const quiet = el("td", "", formatQuietHours(rule.quiet_hours));
    const onCell = el("td");
    const toggle = el("input");
    toggle.type = "checkbox";
    toggle.checked = rule.enabled;
    toggle.setAttribute("aria-label", `Enable ${rule.name}`);
    toggle.onchange = () => handlers.toggle(rule, toggle.checked);
    onCell.append(toggle);
    const actionCell = el("td");
    const remove = el("button", "", "Delete");
    remove.type = "button";
    remove.onclick = () => handlers.remove(rule);
    actionCell.append(remove);
    row.append(name, when, quiet, onCell, actionCell);
    body.append(row);
  }
  table.append(body);
  box.append(table);
  const channels = new Set<string>();
  for (const rule of rules) for (const action of rule.actions) channels.add(action.action_type);
  box.append(
    el(
      "p",
      "ev-note",
      channels.size
        ? `Channels in use: ${[...channels].sort().join(", ")}. Only Telegram sends today.`
        : "Only Telegram sends today; email and webhook are next.",
    ),
  );
  return box;
}

interface ConditionRow {
  root: HTMLElement;
  field: HTMLSelectElement;
  operator: HTMLSelectElement;
  value: HTMLInputElement;
}

function conditionRow(onRemove: () => void): ConditionRow {
  const root = el("p", "desk-position");
  const field = el("select");
  for (const spec of FIELDS) {
    const option = el("option", "", spec.label);
    option.value = spec.field;
    field.append(option);
  }
  const operator = el("select");
  const value = el("input");
  const remove = el("button", "", "Remove");
  remove.type = "button";
  root.append(field, operator, value, remove);

  const row: ConditionRow = { root, field, operator, value };
  const sync = (): void => {
    const spec = fieldSpec(field.value);
    operator.replaceChildren();
    for (const op of spec.operators) {
      const option = el("option", "", OPERATOR_LABELS[op] ?? op);
      option.value = op;
      operator.append(option);
    }
    value.type = spec.numeric ? "number" : "text";
    value.placeholder = spec.hint;
  };
  field.onchange = sync;
  remove.onclick = onRemove;
  sync();
  return row;
}

function buildForm(
  status: HTMLElement,
  saved: () => void,
  saveRule: (payload: RulePayload) => Promise<unknown> = (payload) =>
    mutate("POST", "/api/alerts/rules", payload),
): HTMLElement {
  const box = el("section", "ev-block");
  box.append(el("h2", "ev-block-title", "New rule"));

  const nameRow = el("p", "desk-key");
  const nameLabel = el("label");
  const name = el("input");
  name.type = "text";
  name.placeholder = "Energy pull-outs";
  nameLabel.append("Name", name);
  nameRow.append(nameLabel);

  const rowsHost = el("div");
  const rows: ConditionRow[] = [];
  const addRow = (): void => {
    const row = conditionRow(() => {
      const at = rows.indexOf(row);
      if (at >= 0) rows.splice(at, 1);
      row.root.remove();
    });
    rows.push(row);
    rowsHost.append(row.root);
  };
  addRow();
  const add = el("button", "ai-btn secondary", "Add condition");
  add.type = "button";
  add.onclick = addRow;

  const channelRow = el("p", "desk-key");
  const channelLabel = el("label");
  const channel = el("select");
  for (const option of CHANNELS) {
    const node = el("option", "", option.label);
    node.value = option.id;
    node.disabled = option.disabled;
    channel.append(node);
  }
  channelLabel.append("Channel", channel);
  channelRow.append(channelLabel);

  const quietRow = el("p", "desk-key");
  const quietLabel = el("label");
  const start = el("input");
  const end = el("input");
  for (const input of [start, end]) {
    input.type = "time";
    input.step = "60";
  }
  quietLabel.append("Quiet hours (UTC) from", start, "to", end);
  const clear = el("button", "", "Clear quiet hours");
  clear.type = "button";
  clear.onclick = () => {
    start.value = "";
    end.value = "";
  };
  quietRow.append(quietLabel, clear);

  const save = el("button", "ai-btn", "Save rule");
  save.type = "submit";

  const form = el("form");
  form.append(nameRow, rowsHost, add, channelRow, quietRow, save);
  form.onsubmit = (event) => {
    event.preventDefault();
    status.className = "ev-note";
    status.textContent = "";
    if (!apiKey()) {
      status.className = "warn";
      status.textContent = "No API key. Add it in My Desk, then save again.";
      return;
    }
    save.disabled = true;
    try {
      const payload = buildRule({
        name: name.value,
        conditions: rows.map((row) => ({
          field: row.field.value,
          operator: row.operator.value,
          value: row.value.value,
        })),
        channel: channel.value,
        quietStart: start.value,
        quietEnd: end.value,
      });
      void saveRule(payload)
        .then(() => {
          name.value = "";
          start.value = "";
          end.value = "";
          status.textContent = "Saved. It fires on the next matching event.";
          saved();
        })
        .catch((err: unknown) => {
          status.className = "warn";
          status.textContent = message(err);
        })
        .finally(() => {
          save.disabled = false;
        });
    } catch (err) {
      status.className = "warn";
      status.textContent = message(err);
      save.disabled = false;
    }
  };

  box.append(
    form,
    el(
      "p",
      "ev-note",
      "Conditions are AND-ed. Verdict, sector, topic and event type take one value or a comma-separated any-of list; a ticker condition contains; the score threshold is a lower bound.",
    ),
    el(
      "p",
      "ev-note",
      "Quiet hours use UTC and may cross midnight. Leave both blank to allow alerts at any hour.",
    ),
    el(
      "p",
      "ev-note",
      "Email and webhook channels are next. A rule saved today sends to Telegram with the bot configured on the server.",
    ),
    el("p", "disclaimer", "Research and education only. Not financial advice."),
  );
  return box;
}

/**
 * Mount just the builder, with the save call injectable. The alerts page mounts the same
 * form through `renderAlerts`; a test mounts it here and asserts the payload it sends.
 */
export function mountAlertBuilder(
  root: HTMLElement,
  api: { save: (payload: RulePayload) => Promise<unknown>; onSaved?: () => void } = {
    save: (payload) => mutate("POST", "/api/alerts/rules", payload),
  },
): HTMLElement {
  const status = el("p", "ev-note", "");
  const form = buildForm(
    status,
    () => {
      status.className = "ev-note";
      status.textContent = "Saved. It fires on the next matching event.";
      api.onSaved?.();
    },
    api.save,
  );
  root.replaceChildren(form, status);
  return root;
}

export async function renderAlerts(container: HTMLElement): Promise<void> {
  const page = el("article", "event-page");
  const head = el("header", "ev-head");
  head.append(el("h1", "ev-subject", "Alerts"));
  const status = el("p", "ev-note", "");
  const listHost = el("div");

  const fail = (err: unknown): void => {
    status.className = "warn";
    status.textContent = message(err);
  };

  async function refresh(): Promise<void> {
    try {
      listHost.replaceChildren(
        renderRulesList(await loadRules(), {
          toggle: (rule, enabled) => {
            void mutate("PATCH", `/api/alerts/rules/${encodeURIComponent(rule.id)}`, {
              enabled,
            })
              .then(refresh)
              .catch(fail);
          },
          remove: (rule) => {
            void mutate("DELETE", `/api/alerts/rules/${encodeURIComponent(rule.id)}`)
              .then(refresh)
              .catch(fail);
          },
        }),
      );
    } catch (err) {
      fail(err);
    }
  }

  page.append(
    backLink(),
    head,
    el(
      "p",
      "ev-note",
      "A rule watches every new event and sends when all of its conditions hold. Reads work without a key; saving and deleting need the key from My Desk.",
    ),
    listHost,
    buildForm(status, () => void refresh()),
    status,
  );
  container.replaceChildren(page);
  listHost.replaceChildren(el("p", "empty", "Loading alert rules..."));
  await refresh();
}

export class AlertsPageView {
  readonly el: HTMLElement;

  constructor() {
    this.el = el("div", "ev-host");
    this.el.hidden = true;
  }

  async load(): Promise<void> {
    this.el.hidden = false;
    await renderAlerts(this.el);
  }

  hide(): void {
    this.el.hidden = true;
  }
}
