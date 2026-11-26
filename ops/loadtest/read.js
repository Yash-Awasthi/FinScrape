// Open-loop read load with k6, one metric per endpoint (plan M6.3.3).
//
//   k6 run -e BASE_URL=http://127.0.0.1:8020 -e RPS=500 -e DURATION=10s ops/loadtest/read.js
//
// constant-arrival-rate releases one request every 1/rps seconds from a fixed schedule, so
// a slow server shows up as dropped iterations and a growing queue, never as client slow-down.
import http from "k6/http";
import { Counter, Trend } from "k6/metrics";

const base = __ENV.BASE_URL || "http://127.0.0.1:8010";
const paths = (__ENV.PATHS || "/api/events?limit=50,/api/scenarios")
  .split(",")
  .map((p) => p.trim())
  .filter(Boolean);

function slug(path) {
  const name = path.replace(/[^A-Za-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return name || "root";
}

const latency = {};
const errors = {};
for (const path of paths) {
  latency[path] = new Trend(`latency_${slug(path)}`, true);
  errors[path] = new Counter(`errors_${slug(path)}`);
}

export const options = {
  scenarios: {
    read: {
      executor: "constant-arrival-rate",
      rate: Number(__ENV.RPS || 50),
      timeUnit: "1s",
      duration: __ENV.DURATION || "10s",
      preAllocatedVUs: Number(__ENV.VUS || Math.max(50, Number(__ENV.RPS || 50) / 2)),
      maxVUs: Number(__ENV.MAX_VUS || 4000),
    },
  },
  summaryTrendStats: ["count", "avg", "med", "p(95)", "p(99)", "max"],
};

export default function () {
  const path = paths[__ITER % paths.length];
  const res = http.get(base + path, { timeout: __ENV.TIMEOUT || "60s" });
  latency[path].add(res.timings.duration);
  // A refused connection (status 0) is a failure too: on a starved host it is the signal.
  if (res.status === 0 || res.status >= 500) {
    errors[path].add(1);
  }
}

export function handleSummary(data) {
  return { stdout: summary(data) };
}

function summary(data) {
  const rows = [
    "metric              n    errors     avg      med      p95      p99      max",
  ];
  for (const path of paths) {
    const name = slug(path);
    const trend = data.metrics[`latency_${name}`];
    const errs = data.metrics[`errors_${name}`];
    if (!trend) continue;
    const v = trend.values;
    rows.push(
      `${name.padEnd(18)} ${String(trend.values.count).padStart(5)} ` +
        `${String(errs ? errs.values.count : 0).padStart(8)} ` +
        `${fmt(v.avg)} ${fmt(v.med)} ${fmt(v["p(95)"])} ${fmt(v["p(99)"])} ${fmt(v.max)}`,
    );
  }
  const iter = data.metrics.iterations ? data.metrics.iterations.values.count : 0;
  const dropped = data.metrics.dropped_iterations
    ? data.metrics.dropped_iterations.values.count
    : 0;
  const rps = data.metrics.http_reqs ? data.metrics.http_reqs.values.rate : 0;
  rows.push(
    `iterations ${iter}, dropped ${dropped}, achieved ${rps.toFixed(1)} rps ` +
      `(target ${__ENV.RPS || 50})`,
  );
  return rows.join("\n") + "\n";
}

function fmt(ms) {
  return `${Math.round(Number(ms))}ms`.padStart(8);
}
