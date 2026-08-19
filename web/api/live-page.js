// Serve the latest generated dashboard HTML without creating a Vercel deployment
// for every data collection.  The collection workflows publish site-public to the
// rate-live branch; this stable function reads that branch at request time.
//
// Keep the URL construction server-side.  Only two fixed page names are accepted,
// so callers cannot turn this endpoint into an arbitrary GitHub proxy.

const PAGES = Object.freeze({
  index: "index.html",
  strategy: "strategy.html",
});
const LIVE_BRANCH = "rate-live";
const RELEASE_BRANCH = "rate-data";

const repoSlug = () => {
  const owner = process.env.VERCEL_GIT_REPO_OWNER || "dekt-oss";
  const repo = process.env.VERCEL_GIT_REPO_SLUG || "bank-rate-collector";
  return `${owner}/${repo}`;
};

const rawUrl = (branch, file) =>
  `https://raw.githubusercontent.com/${repoSlug()}/${branch}/site-public/${file}`;

const pageKey = (req) => {
  const value = req.query && req.query.page;
  return Array.isArray(value) ? value[0] : value;
};

const loadPage = async (branch, file) => {
  const response = await fetch(rawUrl(branch, file), {
    cache: "no-store",
    headers: {
      accept: "text/plain,text/html;q=0.9,*/*;q=0.1",
      "user-agent": "bank-rate-collector-live-page",
    },
  });
  if (!response.ok) return { ok: false, status: response.status };
  return { ok: true, status: response.status, text: await response.text(), branch };
};

export default async function handler(req, res) {
  if (req.method !== "GET" && req.method !== "HEAD") {
    res.setHeader("allow", "GET, HEAD");
    return res.status(405).send("Method Not Allowed");
  }

  const key = pageKey(req) || "index";
  const file = PAGES[key];
  if (!file) return res.status(404).send("Not Found");

  let lastStatus = 502;
  for (const branch of [LIVE_BRANCH, RELEASE_BRANCH]) {
    try {
      const loaded = await loadPage(branch, file);
      lastStatus = loaded.status;
      if (!loaded.ok) continue;

      res.setHeader("content-type", "text/html; charset=utf-8");
      res.setHeader("cache-control", "no-store, max-age=0");
      res.setHeader("x-robots-tag", "noindex, nofollow");
      res.setHeader("x-rate-monitor-page-source", loaded.branch);
      if (req.method === "HEAD") return res.status(200).end();
      return res.status(200).send(loaded.text);
    } catch (error) {
      lastStatus = 502;
      console.error(`live page fetch failed (${branch}/${file})`, error);
    }
  }

  return res.status(lastStatus === 404 ? 404 : 502).send(
    lastStatus === 404 ? "Not Found" : "Live dashboard payload is unavailable",
  );
}
