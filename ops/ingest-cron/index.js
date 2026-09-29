// GH_TOKEN: fine-grained PAT for Yash-Awasthi/fin-scrape with Actions read and write.
const DISPATCH =
  "https://api.github.com/repos/Yash-Awasthi/fin-scrape/actions/workflows/ingest.yml/dispatches";

export default {
  async scheduled(_controller, env) {
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
