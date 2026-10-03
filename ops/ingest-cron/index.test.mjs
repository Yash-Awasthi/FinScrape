import assert from "node:assert/strict";
import { test } from "node:test";

import { due } from "./index.mjs";

const at = (iso) => new Date(iso).getTime();

test("daily ingest runs once, at 00:10 UTC", () => {
  assert.deepEqual(due(at("2026-10-05T00:10:00Z"), 24), ["ingest.yml"]);
  assert.deepEqual(due(at("2026-10-05T13:10:00Z"), 24), []);
});

test("hourly ingest runs every hour and keeps the API warm", () => {
  assert.deepEqual(due(at("2026-10-05T13:10:00Z"), 1), ["health", "ingest.yml"]);
  assert.deepEqual(due(at("2026-10-05T13:20:00Z"), 1), ["health"]);
});

test("every 3 hours", () => {
  assert.deepEqual(due(at("2026-10-05T03:10:00Z"), 3), ["ingest.yml"]);
  assert.deepEqual(due(at("2026-10-05T04:10:00Z"), 3), []);
});

test("summary, backup and the Saturday sweep", () => {
  assert.deepEqual(due(at("2026-10-05T02:30:00Z"), 24), ["telegram-summary.yml"]);
  assert.deepEqual(due(at("2026-10-05T21:20:00Z"), 24), ["backup.yml"]);
  assert.deepEqual(due(at("2026-10-10T06:00:00Z"), 24), ["score-week.yml"]);
  assert.deepEqual(due(at("2026-10-05T06:00:00Z"), 24), []);
});

test("a missing or bad value falls back to daily", () => {
  assert.deepEqual(due(at("2026-10-05T00:10:00Z"), Number("x")), ["ingest.yml"]);
  assert.deepEqual(due(at("2026-10-05T01:10:00Z"), undefined), []);
});
