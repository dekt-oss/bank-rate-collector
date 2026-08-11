#!/usr/bin/env node

import fs from "node:fs";
import { chromium } from "playwright";

const baseUrl = (process.env.PRODUCTION_URL || "https://bank-rate-collector.vercel.app").replace(/\/$/, "");
const outJson = process.env.PERF_JSON || "performance-baseline.json";
const outMd = process.env.PERF_MD || "performance-baseline.md";

const scenarios = [
  {
    name: "desktop-fast",
    viewport: { width: 1440, height: 900 },
    mobile: false,
    latency: 5,
    downloadMbps: 100,
    uploadMbps: 20,
  },
  {
    name: "mobile-lte",
    viewport: { width: 390, height: 844 },
    mobile: true,
    latency: 40,
    downloadMbps: 10,
    uploadMbps: 5,
  },
  {
    name: "mobile-slow-3g",
    viewport: { width: 390, height: 844 },
    mobile: true,
    latency: 300,
    downloadMbps: 1.6,
    uploadMbps: 0.75,
  },
];

const throughput = (mbps) => Math.round((mbps * 1_000_000) / 8);
const round = (value) => (value == null ? null : Math.round(value * 10) / 10);

async function heapBytes(page) {
  return page.evaluate(() => performance.memory?.usedJSHeapSize ?? null);
}

async function runScenario(browser, scenario) {
  const context = await browser.newContext({
    viewport: scenario.viewport,
    isMobile: scenario.mobile,
    deviceScaleFactor: scenario.mobile ? 2 : 1,
    locale: "ko-KR",
  });
  const page = await context.newPage();
  const session = await context.newCDPSession(page);
  await session.send("Network.enable");
  await session.send("Network.setCacheDisabled", { cacheDisabled: true });
  await session.send("Network.emulateNetworkConditions", {
    offline: false,
    latency: scenario.latency,
    downloadThroughput: throughput(scenario.downloadMbps),
    uploadThroughput: throughput(scenario.uploadMbps),
    connectionType: scenario.name.includes("lte") ? "cellular4g" : scenario.name.includes("3g") ? "cellular3g" : "ethernet",
  });

  const navigationStarted = Date.now();
  await page.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded", timeout: 90_000 });
  await page.waitForFunction(
    () => {
      const count = document.getElementById("count");
      const mine = document.getElementById("mine");
      const rows = document.getElementById("rows");
      return count && count.textContent.trim() !== "—" && mine && !mine.disabled && rows && rows.children.length > 0;
    },
    { timeout: 90_000 },
  );
  const initialRenderMs = Date.now() - navigationStarted;
  const heapAfterRender = await heapBytes(page);

  const resource = await page.evaluate(() => {
    const entry = performance
      .getEntriesByType("resource")
      .find((item) => item.name.includes("/data/table.json"));
    if (!entry) return null;
    return {
      duration: entry.duration,
      transferSize: entry.transferSize,
      encodedBodySize: entry.encodedBodySize,
      decodedBodySize: entry.decodedBodySize,
    };
  });

  const parse = await page.evaluate(async () => {
    const response = await fetch("data/table.json");
    const text = await response.text();
    const started = performance.now();
    const value = JSON.parse(text);
    const elapsed = performance.now() - started;
    return { ms: elapsed, rows: Array.isArray(value) ? value.length : value.table?.length ?? null };
  });
  const heapAfterParse = await heapBytes(page);

  const initialCount = await page.locator("#count").textContent();
  const filterStarted = Date.now();
  await page.locator("#q").fill("__perf_no_match__");
  await page.waitForFunction(
    (before) => document.getElementById("count")?.textContent !== before,
    initialCount,
    { timeout: 30_000 },
  );
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const filterLatencyMs = Date.now() - filterStarted;
  const heapAfterFilter = await heapBytes(page);

  const finalCount = await page.locator("#count").textContent();
  const peakHeapBytes = Math.max(...[heapAfterRender, heapAfterParse, heapAfterFilter].filter((v) => v != null));

  await context.close();
  return {
    scenario: scenario.name,
    viewport: scenario.viewport,
    latency_ms: scenario.latency,
    download_mbps: scenario.downloadMbps,
    initial_render_ms: initialRenderMs,
    table_resource_ms: round(resource?.duration),
    table_transfer_bytes: resource?.transferSize ?? null,
    table_encoded_bytes: resource?.encodedBodySize ?? null,
    table_decoded_bytes: resource?.decodedBodySize ?? null,
    json_parse_ms: round(parse.ms),
    parsed_rows: parse.rows,
    filter_latency_ms: filterLatencyMs,
    filter_count_before: initialCount?.trim() ?? null,
    filter_count_after: finalCount?.trim() ?? null,
    peak_heap_bytes: Number.isFinite(peakHeapBytes) ? peakHeapBytes : null,
  };
}

const browser = await chromium.launch({
  headless: true,
  args: ["--enable-precise-memory-info"],
});

const results = [];
try {
  for (const scenario of scenarios) {
    console.log(`measuring ${scenario.name}...`);
    const result = await runScenario(browser, scenario);
    results.push(result);
    console.log(JSON.stringify(result));
  }
} finally {
  await browser.close();
}

const payload = {
  measured_at: new Date().toISOString(),
  production_url: baseUrl,
  scenarios: results,
};
fs.writeFileSync(outJson, `${JSON.stringify(payload, null, 2)}\n`);

const mib = (bytes) => (bytes == null ? "—" : `${(bytes / 1024 / 1024).toFixed(2)} MiB`);
const md = [
  "# Production browser performance baseline",
  "",
  `- measured_at: ${payload.measured_at}`,
  `- production: ${baseUrl}`,
  "",
  "| scenario | initial render | table transfer | decoded JSON | JSON parse | filter | peak JS heap |",
  "|---|---:|---:|---:|---:|---:|---:|",
  ...results.map((r) =>
    `| ${r.scenario} | ${r.initial_render_ms} ms | ${mib(r.table_transfer_bytes)} | ${mib(r.table_decoded_bytes)} | ${r.json_parse_ms} ms | ${r.filter_latency_ms} ms | ${mib(r.peak_heap_bytes)} |`,
  ),
  "",
  "This is a measurement artifact, not a hard pass/fail budget. Structural changes such as sharding are decided from the measured bottleneck rather than raw file size alone.",
  "",
].join("\n");
fs.writeFileSync(outMd, md);
console.log(md);
