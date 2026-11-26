import { readFileSync } from "node:fs";
import { expect, it } from "vite-plus/test";

import { parseRoute } from "./routes";

it("reads an event path, and refuses anything that is not an integer id", () => {
  expect(parseRoute("/app/event/12")).toEqual({ kind: "event", id: 12 });
  expect(parseRoute("/app/event/12/")).toEqual({ kind: "event", id: 12 });
  expect(parseRoute("/app/event/12x")).toBeNull();
  expect(parseRoute("/app/event/")).toBeNull();
  expect(parseRoute("/app/")).toBeNull();
  expect(parseRoute("/", "#today")).toBeNull();
});

it("reads a scenario path", () => {
  expect(parseRoute("/app/scenario/s12")).toEqual({ kind: "scenario", id: "s12" });
  expect(parseRoute("/app/scenario/12")).toBeNull();
});

it("accepts the hash form so a host without a rewrite still deep-links", () => {
  expect(parseRoute("/app/", "#/app/event/9")).toEqual({ kind: "event", id: 9 });
});

it("the deployed host rewrites a detail path to the dashboard shell", () => {
  const rules = readFileSync("public/_redirects", "utf8");
  expect(rules).toContain("/app/*  /app/index.html  200");
});
