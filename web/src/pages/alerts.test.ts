import { beforeEach, expect, it } from "vite-plus/test";

import {
  buildRule,
  conditionPayload,
  FIELDS,
  mountAlertBuilder,
  quietHoursValue,
  type RulePayload,
} from "./alerts";

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("worldfin.apiKey", "test-key");
  document.body.replaceChildren();
});

const ONE = { field: "verdict", operator: "eq", value: "INVEST" };

it("buildRule assembles the POST body the route takes", () => {
  const body = buildRule({
    name: " Energy pull-outs ",
    conditions: [
      ONE,
      { field: "tickers", operator: "contains", value: "XOM" },
      { field: "signal_score", operator: "gte", value: "4" },
      { field: "sector", operator: "in", value: "energy, shipping" },
    ],
  });
  expect(body.name).toBe("Energy pull-outs");
  expect(body.conditions).toEqual([
    { field: "verdict", operator: "eq", value: "INVEST" },
    { field: "tickers", operator: "contains", value: "XOM" },
    { field: "signal_score", operator: "gte", value: 4 },
    { field: "sector", operator: "in", value: ["energy", "shipping"] },
  ]);
  expect(body.actions).toEqual([{ action_type: "telegram", config: {} }]);
  expect("quiet_hours" in body).toBe(false);
});

it("buildRule carries the channel and the quiet window when given", () => {
  const body = buildRule({
    name: "Quiet",
    conditions: [ONE],
    channel: "webhook",
    quietStart: "22:00",
    quietEnd: "06:00",
  });
  expect(body.actions).toEqual([{ action_type: "webhook", config: {} }]);
  expect(body.quiet_hours).toEqual({ start: "22:00", end: "06:00" });
});

it("buildRule refuses a nameless, conditionless or unsaveable rule", () => {
  expect(() => buildRule({ name: "  ", conditions: [ONE] })).toThrow("Name the rule first");
  expect(() => buildRule({ name: "x", conditions: [] })).toThrow("Add at least one condition");
  expect(() =>
    buildRule({ name: "x", conditions: [{ field: "verdict", operator: "eq", value: " " }] }),
  ).toThrow("Add at least one condition");
  expect(() =>
    buildRule({ name: "x", conditions: [ONE], quietStart: "9:00", quietEnd: "17:00" }),
  ).toThrow("HH:MM");
  expect(() =>
    buildRule({ name: "x", conditions: [ONE], quietStart: "22:00", quietEnd: "22:00" }),
  ).toThrow("same");
  expect(() => buildRule({ name: "x", conditions: [ONE], quietStart: "22:00" })).toThrow(
    "both a start and an end",
  );
});

it("an operator the engine rejects is refused before it is sent", () => {
  expect(() => conditionPayload("verdict", "contains", "INVEST")).toThrow("does not support");
  expect(quietHoursValue("", "")).toBeNull();
});

it("mounts one row per condition field with operator and channel choices", () => {
  const root = mountAlertBuilder(document.createElement("div"), {
    save: async () => ({ ok: true }),
  });
  const selects = root.querySelectorAll("select");
  // Field select, operator select, channel select.
  expect(selects).toHaveLength(3);
  const fields = [...(selects[0] as HTMLSelectElement).options].map((o) => o.value);
  expect(fields).toEqual(FIELDS.map((f) => f.field));
  const channelOptions = [...(selects[2] as HTMLSelectElement).options];
  const email = channelOptions.find((o) => o.value === "email");
  const webhook = channelOptions.find((o) => o.value === "webhook");
  expect(email?.textContent).toContain("next");
  expect(email?.disabled).toBe(true);
  expect(webhook?.disabled).toBe(true);
  expect((selects[2] as HTMLSelectElement).value).toBe("telegram");
  // Quiet-hours clock inputs and the not-advice line live where the rule is saved.
  expect(root.querySelectorAll("input[type='time']")).toHaveLength(2);
  expect(root.querySelector(".disclaimer")?.textContent).toContain("Not financial advice");
});

it("adds and removes condition rows", () => {
  const root = mountAlertBuilder(document.createElement("div"), { save: async () => ({}) });
  expect(root.querySelectorAll("select").length).toBe(3);
  const add = [...root.querySelectorAll("button")].find((b) => b.textContent === "Add condition")!;
  add.click();
  expect(root.querySelectorAll("p.desk-position").length).toBe(2);
  const remove = [...root.querySelectorAll("button")].filter((b) => b.textContent === "Remove")[0];
  remove.click();
  expect(root.querySelectorAll("p.desk-position").length).toBe(1);
});

it("submits the built payload and reports the save", async () => {
  const sent: RulePayload[] = [];
  const root = mountAlertBuilder(document.createElement("div"), {
    save: async (payload) => {
      sent.push(payload);
      return { ok: true };
    },
  });
  const inputs = root.querySelectorAll("input");
  const name = inputs[0] as HTMLInputElement;
  const value = inputs[1] as HTMLInputElement;
  name.value = "Energy";
  value.value = "energy";
  const channel = root.querySelectorAll("select")[2] as HTMLSelectElement;
  channel.value = "telegram";
  (root.querySelector("form") as HTMLFormElement).requestSubmit();
  await Promise.resolve();
  await Promise.resolve();
  expect(sent).toHaveLength(1);
  expect(sent[0].name).toBe("Energy");
  expect(sent[0].conditions).toEqual([{ field: "verdict", operator: "eq", value: "energy" }]);
  expect(root.textContent).toContain("Saved.");
});

it("shows the validation sentence instead of sending", async () => {
  let calls = 0;
  const root = mountAlertBuilder(document.createElement("div"), {
    save: async () => {
      calls += 1;
      return {};
    },
  });
  (root.querySelector("form") as HTMLFormElement).requestSubmit();
  await Promise.resolve();
  expect(calls).toBe(0);
  expect(root.querySelector(".warn")?.textContent).toContain("Name the rule first");
});
