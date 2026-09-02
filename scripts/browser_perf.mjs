#!/usr/bin/env node

import fs from "node:fs";
import zlib from "node:zlib";
import { chromium } from "playwright";

const baseUrl = (process.env.PRODUCTION_URL || "https://bank-rate-collector.vercel.app").replace(/\/$/, "");
const outJson = process.env.PERF_JSON || "performance-baseline.json";
const outMd = process.env.PERF_MD || "performance-baseline.md";
const scenarios = [
  { name: "desktop-fast", viewport: { width: 1440, height: 900 }, mobile: false, latency: 5, downloadMbps: 100, uploadMbps: 20 },
  { name: "mobile-lte", viewport: { width: 390, height: 844 }, mobile: true, latency: 40, downloadMbps: 10, uploadMbps: 5 },
  { name: "mobile-slow-3g", viewport: { width: 390, height: 844 }, mobile: true, latency: 300, downloadMbps: 1.6, uploadMbps: 0.75 },
];
const throughput = (mbps) => Math.round((mbps * 1_000_000) / 8);
const round = (value) => (value == null ? null : Math.round(value * 10) / 10);
const heapBytes = (page) => page.evaluate(() => performance.memory?.usedJSHeapSize ?? null);
const parseTableResponse = async (response) => {
  const body = await response.body();
  const isGzip = body.length >= 2 && body[0] === 0x1f && body[1] === 0x8b;
  const jsonBytes = isGzip ? zlib.gunzipSync(body) : body;
  return JSON.parse(jsonBytes.toString("utf8"));
};

async function runScenario(browser, scenario) {
  const context = await browser.newContext({ viewport: scenario.viewport, isMobile: scenario.mobile, deviceScaleFactor: scenario.mobile ? 2 : 1, locale: "ko-KR" });
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

  const tableResponse = page.waitForResponse(
    (response) => response.url().includes("/data/table.json") && response.ok(),
    { timeout: 180_000 },
  );
  const navigationStarted = Date.now();
  await page.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded", timeout: 180_000 });
  await page.waitForFunction(() => {
    const count = document.getElementById("count");
    const rows = document.getElementById("rows");
    const deposit = document.querySelector('[data-product-family-toggle="deposit"]');
    const savings = document.querySelector('[data-product-family-toggle="savings"]');
    return count?.textContent.trim() !== "—" && rows?.children.length > 0 && deposit && savings;
  }, undefined, { timeout: 180_000 });
  const initialRenderMs = Date.now() - navigationStarted;
  const heapAfterRender = await heapBytes(page);

  const response = await tableResponse;
  const payload = await parseTableResponse(response);
  const parsedRows = Array.isArray(payload) ? payload.length : payload.rows?.length ?? null;
  const resource = await page.evaluate(() => {
    const entry = performance.getEntriesByType("resource").find((item) => item.name.includes("/data/table.json"));
    return entry ? { duration: entry.duration, transferSize: entry.transferSize, encodedBodySize: entry.encodedBodySize, decodedBodySize: entry.decodedBodySize } : null;
  });

  const initialCount = (await page.locator("#count").textContent())?.trim() ?? null;
  const savings = page.locator('[data-product-family-toggle="savings"]');
  if (!(await savings.isVisible())) throw new Error("current Search savings family control is not visible");
  const filterStarted = performance.now();
  await savings.check();
  await page.waitForFunction(
    (before) => document.getElementById("count")?.textContent.trim() !== before,
    initialCount,
    { timeout: 60_000 },
  );
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const filterLatencyMs = performance.now() - filterStarted;
  const heapAfterFilter = await heapBytes(page);
  const finalCount = (await page.locator("#count").textContent())?.trim() ?? null;
  const peakHeapBytes = Math.max(...[heapAfterRender, heapAfterFilter].filter((v) => v != null));
  await context.close();

  return {
    scenario: scenario.name, viewport: scenario.viewport, latency_ms: scenario.latency, download_mbps: scenario.downloadMbps,
    initial_render_ms: initialRenderMs, table_resource_ms: round(resource?.duration), table_transfer_bytes: resource?.transferSize ?? null,
    table_encoded_bytes: resource?.encodedBodySize ?? null, table_decoded_bytes: resource?.decodedBodySize ?? null,
    parsed_rows: parsedRows, filter_latency_ms: round(filterLatencyMs), filter_count_before: initialCount,
    filter_count_after: finalCount, peak_heap_bytes: Number.isFinite(peakHeapBytes) ? peakHeapBytes : null,
  };
}

const browser = await chromium.launch({ headless: true, args: ["--enable-precise-memory-info"] });
const results = [];
try {
  for (const scenario of scenarios) {
    const result = await runScenario(browser, scenario);
    results.push(result);
    console.log(JSON.stringify(result));
  }
} finally { await browser.close(); }

const payload = { measured_at: new Date().toISOString(), production_url: baseUrl, scenarios: results };
fs.writeFileSync(outJson, `${JSON.stringify(payload, null, 2)}\n`);
const mib = (bytes) => (bytes == null ? "—" : `${(bytes / 1024 / 1024).toFixed(2)} MiB`);
const md = [
  "# Search browser performance", "", `- measured_at: ${payload.measured_at}`, `- target: ${baseUrl}`, "",
  "| scenario | initial render | table transfer | decoded JSON | filter | peak JS heap |",
  "|---|---:|---:|---:|---:|---:|",
  ...results.map((r) => `| ${r.scenario} | ${r.initial_render_ms} ms | ${mib(r.table_transfer_bytes)} | ${mib(r.table_decoded_bytes)} | ${r.filter_latency_ms} ms | ${mib(r.peak_heap_bytes)} |`), "",
].join("\n");
fs.writeFileSync(outMd, md);
console.log(md);
