// Serve the latest generated dashboard HTML without creating a Vercel deployment
// for every data collection.  Collection workflows keep replacing the rate-data
// branch; this stable function reads that branch at request time instead of serving
// the snapshot baked into the last Vercel deployment.
//
// Keep URL construction server-side. Only two fixed page names are accepted, so
// callers cannot turn this endpoint into an arbitrary GitHub proxy.

const PAGES = Object.freeze({
  index: "index.html",
  strategy: "strategy.html",
});
const LIVE_BRANCH = "rate-data";

const repoSlug = () => {
  const owner = process.env.VERCEL_GIT_REPO_OWNER || "dekt-oss";
  const repo = process.env.VERCEL_GIT_REPO_SLUG || "bank-rate-collector";
  return `${owner}/${repo}`;
};

const rawUrl = (file) =>
  `https://raw.githubusercontent.com/${repoSlug()}/${LIVE_BRANCH}/site-public/${file}`;

const pageKey = (req) => {
  const value = req.query && req.query.page;
  return Array.isArray(value) ? value[0] : value;
};

export default async function handler(req, res) {
  if (req.method !== "GET" && req.method !== "HEAD") {
    res.setHeader("allow", "GET, HEAD");
    return res.status(405).send("Method Not Allowed");
  }

  const key = pageKey(req) || "index";
  const file = PAGES[key];
  if (!file) return res.status(404).send("Not Found");

  try {
    const response = await fetch(rawUrl(file), {
      cache: "no-store",
      headers: {
        accept: "text/plain,text/html;q=0.9,*/*;q=0.1",
        "user-agent": "bank-rate-collector-live-page",
      },
    });
    if (!response.ok) {
      return res.status(response.status === 404 ? 404 : 502).send(
        response.status === 404 ? "Not Found" : "Live dashboard payload is unavailable",
      );
    }

    res.setHeader("content-type", "text/html; charset=utf-8");
    res.setHeader("cache-control", "no-store, max-age=0");
    res.setHeader("x-robots-tag", "noindex, nofollow");
    res.setHeader("x-rate-monitor-page-source", LIVE_BRANCH);
    if (req.method === "HEAD") return res.status(200).end();
    return res.status(200).send(await response.text());
  } catch (error) {
    console.error(`live page fetch failed (${LIVE_BRANCH}/${file})`, error);
    return res.status(502).send("Live dashboard payload is unavailable");
  }
}
