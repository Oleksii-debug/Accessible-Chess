"use strict";

/*
 * Real Chromium/Windows proof for the existing canonical
 * BrowserLocalVideoPlaybackAdapter, not a second media application.
 * Usage: node tests/js/section47_canonical_browser_playback.js /verified/original.webm
 * The test uses a temporary file:// page colocated with a verified original,
 * not an unsafe privileged switch and not a synthetic video substitute.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { chromium } = require("playwright");

async function main() {
  const input = process.argv[2];
  if (!input || !/\.(webm|mp4)$/i.test(input) || !fs.statSync(input).isFile())
    throw new Error("original MP4/WebM fixture missing");
  const source = path.resolve(input);
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), "ac-section47-browser-"));
  let browser;
  try {
    const filename = "original" + path.extname(source).toLowerCase();
    fs.copyFileSync(source, path.join(workspace, filename));
    const localJs = fs.readFileSync(path.join(__dirname, "../../web/local_video_playback_adapter.js"), "utf8");
    fs.writeFileSync(path.join(workspace, "local_video_playback_adapter.js"), localJs);
    fs.writeFileSync(path.join(workspace, "test.html"),
      '<!doctype html><html lang="uk"><meta charset="utf-8"><div id="mount"></div>' +
      '<button id="play">Відтворити</button><button id="pause">Пауза</button>' +
      '<script src="local_video_playback_adapter.js"></script>' +
      '<script>let p=null;window.state=[];function open(){p=new AccessibleChessLocalVideoPlayback.' +
      'BrowserLocalVideoPlaybackAdapter({element:document.getElementById("mount"),sourceUrl:' +
      JSON.stringify(pathToFileURL(path.join(workspace, filename)).toString()) +
      ',sourceId:"local:sha256:fixture-qualified-test",onSnapshot:s=>window.state.push(s)});' +
      'document.getElementById("play").onclick=()=>p.play();' +
      'document.getElementById("pause").onclick=()=>p.pause();}' +
      'window.openMedia=open;open();</script></html>'
    );
    browser = await chromium.launch({headless:true});
    const page = await browser.newPage();
    await page.goto(pathToFileURL(path.join(workspace, "test.html")).toString(), {
      waitUntil:"domcontentloaded", timeout:30000,
    });
    const video = page.locator("#section47-local-video");
    await video.waitFor({state:"attached"});
    await page.waitForFunction(() => {
      const v=document.getElementById("section47-local-video");
      return v && v.readyState>=2 && Number.isFinite(v.duration) && v.duration>0;
    }, null, {timeout:45000});
    await page.locator("#play").click();
    await page.waitForFunction(() => document.getElementById("section47-local-video").currentTime>.2,
      null, {timeout:15000});
    await page.locator("#pause").click();
    const paused = await video.evaluate(v=>({paused:v.paused,time:v.currentTime,duration:v.duration,error:v.error&&v.error.code}));
    assert(paused.paused && paused.time>.2 && paused.error===null,"real play/pause failed");
    await video.evaluate(v=>{v.currentTime=Math.min(2,v.duration/3);});
    await page.waitForFunction(() => !document.getElementById("section47-local-video").seeking,
      null, {timeout:15000});
    await page.locator("#section47-local-video-rate").selectOption("1.5");
    await page.locator("#section47-local-video-volume").evaluate(input=>{
      input.value="35";input.dispatchEvent(new Event("input",{bubbles:true}));
    });
    const qualified=await video.evaluate(v=>({
      time:v.currentTime,rate:v.playbackRate,volume:v.volume,duration:v.duration,
      error:v.error&&v.error.code
    }));
    assert(qualified.time>0 && qualified.rate===1.5 && Math.abs(qualified.volume-.35)<.001);
    assert.equal(qualified.error,null);
    const snapshots=await page.evaluate(()=>window.state);
    assert(snapshots.some(s=>s.sourceId==="local:sha256:fixture-qualified-test"));
    assert(snapshots.some(s=>s.playbackState==="playing"));
    assert(snapshots.some(s=>s.playbackState==="paused"));
    await page.evaluate(()=>{p.destroy();window.openMedia();});
    await page.waitForFunction(()=>
      !!document.getElementById("section47-local-video") &&
      document.getElementById("section47-local-video").readyState>=2,
      null,{timeout:45000});
    const restarted=await video.evaluate(v=>({duration:v.duration,error:v.error&&v.error.code}));
    assert(restarted.duration>0 && restarted.error===null,"reopen after destroy failed");
    console.log(JSON.stringify({
      evidence_class:"REAL_LOCAL_CHROMIUM_DECODE",
      status:"PASS", format:path.extname(source).slice(1),
      source_bytes:fs.statSync(source).size,
      playback_seconds:paused.time,
      seek_seconds:qualified.time,
      playback_rate:qualified.rate,
      volume_percent:Math.round(qualified.volume*100),
      restart:"PASS", codec_error:null,
      canonical_media_chess_position:"NOT_RUN",
      windows_packaged_exe:"NOT_RUN",
    }));
  } finally {
    if (browser) await browser.close();
    fs.rmSync(workspace,{recursive:true,force:true});
  }
}
main().catch(error=>{
  console.error(JSON.stringify({
    evidence_class:"REAL_LOCAL_CHROMIUM_DECODE",status:"FAILED_OR_INCONCLUSIVE",
    reason:String(error && error.message || error).slice(0,260),
  }));
  process.exitCode=1;
});
