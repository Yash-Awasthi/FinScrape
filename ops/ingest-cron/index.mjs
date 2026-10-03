// The only scheduler: GitHub turns off schedules in a public repo after 60 days without
// commits, so this Worker dispatches every timed workflow from one 10-minute cron.
// GH_TOKEN: fine-grained PAT for Yash-Awasthi/fin-scrape with Actions read and write.
// INGEST_EVERY_HOURS (wrangler.jsonc vars): 24 = daily at 00:10 UTC, 1 = hourly for demos.
const DISPATCH = (workflow) =>
  `https://api.github.com/repos/Yash-Awasthi/fin-scrape/actions/workflows/${workflow}/dispatches`;
const HEALTH = "https://winfin-api.onrender.com/health";

export const hours = (value) => (Number.isInteger(value) && value > 0 ? value : 24);

// Jobs due in the 10-minute slot starting at `time` (ms). Render's free plan sleeps after
// 15 idle minutes; it is kept warm only in hourly mode, which spends its free hours.
export function due(time, everyHours) {
  const d = new Date(time);
  const [day, hour, minute] = [d.getUTCDay(), d.getUTCHours(), d.getUTCMinutes()];
  const every = hours(everyHours);
  const jobs = [];
  if (every <= 1) jobs.push("health");
  if (minute === 10 && hour % every === 0) jobs.push("ingest.yml");
  if (hour === 2 && minute === 30) jobs.push("telegram-summary.yml");
  if (hour === 21 && minute === 20) jobs.push("backup.yml");
  if (day === 6 && hour === 6 && minute === 0) jobs.push("score-week.yml");
  return jobs;
}

export default {
  async scheduled(controller, env) {
    const slot = Math.floor(controller.scheduledTime / 600_000) * 600_000;
    const every = hours(Number(env.INGEST_EVERY_HOURS));
    for (const job of due(slot, every)) {
      if (job === "health") {
        await fetch(HEALTH, { headers: { "User-Agent": "winfin-keep-warm" } });
        continue;
      }
      const res = await fetch(DISPATCH(job), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GH_TOKEN}`,
          Accept: "application/vnd.github+json",
          "User-Agent": "winfin-ingest-cron",
        },
        // Only ingest declares an input; GitHub rejects inputs a workflow does not declare.
        body: JSON.stringify(
          job === "ingest.yml"
            ? { ref: "master", inputs: { every_hours: String(every) } }
            : { ref: "master" },
        ),
      });
      if (res.status !== 204) throw new Error(`dispatch ${job} ${res.status}: ${await res.text()}`);
    }
  },
};
