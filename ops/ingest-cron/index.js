// GH_TOKEN: fine-grained PAT for Yash-Awasthi/fin-scrape with Actions read and write.
const DISPATCH =
  "https://api.github.com/repos/Yash-Awasthi/fin-scrape/actions/workflows/ingest.yml/dispatches";
// Render's free plan sleeps after 15 idle minutes; a ping every 10 keeps it warm.
const HEALTH = "https://winfin-api.onrender.com/health";
const PING_CRON = "*/10 * * * *";

export default {
  async scheduled(controller, env) {
    if (controller.cron === PING_CRON) {
      await fetch(HEALTH, { headers: { "User-Agent": "winfin-keep-warm" } });
      return;
    }
    const res = await fetch(DISPATCH, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "winfin-ingest-cron",
      },
      body: JSON.stringify({ ref: "master" }),
    });
    if (res.status !== 204) throw new Error(`dispatch ${res.status}: ${await res.text()}`);
  },
};
