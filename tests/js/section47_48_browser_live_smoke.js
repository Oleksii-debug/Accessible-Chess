"use strict";

/**
 * Real-browser qualification. Requires separately installed Playwright Chromium.
 * This is NOT a deterministic mock test and must not be marked PASS on provider
 * or codec error. Never downloads, intercepts, or caches YouTube video bytes.
 *
 * node tests/js/section47_48_browser_live_smoke.js local /path/to/commons/webm
 * node tests/js/section47_48_browser_live_smoke.js youtube k4BS-4O1iI0
 */
const assert = require("node:assert/strict");
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "../..");
const assets = new Map([
  ["/real_media_workbench.html", "web/real_media_workbench.html"],
  ["/real_media_workbench.js", "web/real_media_workbench.js"],
  ["/youtube_iframe_playback_adapter.js", "web/youtube_iframe_playback_adapter.js"],
]);

async function startServer() {
  const server = http.createServer((request, response) => {
    const resource = assets.get((request.url || "").split("?")[0]);
    if (!resource || request.method !== "GET") {
      response.writeHead(404); response.end("Not found"); return;
    }
    const absolute = path.join(root, resource);
    if (!fs.statSync(absolute).isFile()) {
      response.writeHead(404); response.end("Not found"); return;
    }
    response.setHeader("Cache-Control", "no-store");
    response.setHeader("Content-Type", resource.endsWith(".html") ?
      "text/html; charset=utf-8" : "text/javascript; charset=utf-8");
    fs.createReadStream(absolute).pipe(response);
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return { server, url: "http://127.0.0.1:" + server.address().port +
    "/real_media_workbench.html" };
}
async function testLocal(page, filePath) {
  if (!fs.statSync(filePath).isFile()) throw Error("real source file is missing");
  await page.locator("#real-media-file").setInputFiles(filePath);
  await page.waitForFunction(() => {
    const v = document.querySelector("#real-media-video");
    return v.readyState >= 2 && Number.isFinite(v.duration) && v.duration > 0;
  }, null, { timeout: 40000 });
  let status = await page.locator("#real-media-status").innerText();
  assert(!status.includes("не підтримується"), "real browser rejects codec");
  // Start a genuine media decode/playback path, not an HTML mock.
  await page.locator("#real-media-video").evaluate(video => video.play());
  await page.waitForFunction(() => document.querySelector("#real-media-video").currentTime > 0.2,
    null, { timeout: 12000 });
  await page.locator("#real-media-video").evaluate(video => video.pause());
  const initial = await page.locator("#real-media-video").evaluate(video => ({
    time: video.currentTime, duration: video.duration, paused: video.paused,
    error: video.error && video.error.code,
  }));
  assert(initial.paused && initial.time > 0.2 && !initial.error, "real media pause failure");
  await page.locator("#real-media-video").evaluate(video => {
    video.currentTime = Math.min(2, video.duration / 3);
  });
  await page.waitForFunction(() => {
    const v = document.querySelector("#real-media-video");
    return !v.seeking && v.currentTime > 0;
  });
  await page.locator("#real-media-rewind").click();
  await page.locator("#real-media-forward").click();
  await page.locator("#real-media-rate").selectOption("1.5");
  await page.locator("#real-media-volume").evaluate(slider => {
    slider.value = "35";
    slider.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const final = await page.locator("#real-media-video").evaluate(video => ({
    time: video.currentTime, duration: video.duration,
    playbackRate: video.playbackRate, volume: video.volume,
    error: video.error && video.error.code,
  }));
  assert.equal(final.playbackRate, 1.5);
  assert(Math.abs(final.volume - .35) < .001);
  assert.equal(final.error, null);
  // Repeat opening of an already obtained original; resources must be retired.
  await page.locator("#real-media-file").setInputFiles(filePath);
  await page.waitForFunction(() => document.querySelector("#real-media-video").readyState >= 2);
  status = await page.locator("#real-media-status").innerText();
  assert(!status.includes("не підтримується"), "reopen failed");
  return { evidence_class: "REAL_BROWSER_LOCAL_FILE", status: "PASS",
    filename: path.basename(filePath), initial, final, reopen: "PASS" };
}
async function testYouTube(page, id) {
  assert(/^[A-Za-z0-9_-]{11}$/.test(id), "invalid source ID");
  await page.locator("#real-youtube-url").fill("https://www.youtube.com/watch?v=" + id);
  await page.locator("#real-youtube-open").click();
  await page.waitForFunction(() => {
    const text = document.querySelector("#real-youtube-status").textContent;
    return text.includes("YouTube:") || text.includes("не вдалося") ||
      text.includes("відхилив") || text.includes("немає") || text.includes("Немає");
  }, null, { timeout: 40000 });
  const first = await page.locator("#real-youtube-status").innerText();
  if (!first.includes("YouTube:")) throw Error("LIVE_PROVIDER_NOT_READY: " + first);
  const iframe = page.locator("#real-youtube-player iframe");
  await iframe.waitFor({ state: "attached", timeout: 15000 });
  await page.locator("#real-youtube-play").click();
  await page.waitForFunction(() => {
    const state = document.querySelector("#real-youtube-status").textContent;
    return state.includes("YouTube: playing") ||
      state.includes("відхилив") || state.includes("не виконав");
  }, null, { timeout: 35000 });
  const playing = await page.locator("#real-youtube-status").innerText();
  if (!playing.includes("playing")) throw Error("LIVE_PLAYBACK_NOT_CONFIRMED: " + playing);
  const start = Number(/Час YouTube: (\d+(?:\.\d+)?) с/.exec(await page.locator("#real-youtube-time").innerText())?.[1]);
  await page.waitForTimeout(2500);
  const later = await page.locator("#real-youtube-time").innerText();
  const end = Number(/Час YouTube: (\d+(?:\.\d+)?) с/.exec(later)?.[1]);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
    throw Error("LIVE_TIME_NOT_ADVANCING: " + later);
  }
  await page.locator("#real-youtube-pause").click();
  return { evidence_class: "LIVE_PROVIDER_YOUTUBE_IFRAME", status: "PASS",
    video_id: id, iframe_present: true, initial_seconds: start, subsequent_seconds: end,
    paused_command_sent: true };
}
async function main() {
  const [mode, source] = process.argv.slice(2);
  if (!["local", "youtube"].includes(mode) || !source) throw Error("usage: local FILE / youtube VIDEO_ID");
  const {server,url} = await startServer();
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    page.on("pageerror", error => process.stderr.write("browser page error: " + error.message + "\n"));
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 40000 });
    const result = mode === "local" ? await testLocal(page, path.resolve(source)) :
      await testYouTube(page, source);
    console.log(JSON.stringify(result));
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}
main().catch(error => {
  console.error(JSON.stringify({
    evidence_class: process.argv[2] === "youtube" ? "LIVE_PROVIDER_YOUTUBE_IFRAME" :
      "REAL_BROWSER_LOCAL_FILE",
    status: "FAILED_OR_INCONCLUSIVE", error_type: error.name, reason: error.message.slice(0, 180),
  }));
  process.exitCode = 1;
});
