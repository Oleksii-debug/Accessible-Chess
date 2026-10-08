"use strict";
// Pure deterministic tests. Browser hardware playback and LIVE YouTube are separate evidence.
const fs = require("fs");
const vm = require("vm");
const assert = require("assert").strict;

class FakeNode {
  constructor(tag = "div") {
    this.tagName = tag;
    this.value = "";
    this.textContent = "";
    this.children = [];
    this.listeners = {};
    this.files = [];
  }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  replaceChildren(...children) { this.children = children; }
  appendChild(child) { this.children.push(child); return child; }
  emit(name, extra = {}) {
    if (this.listeners[name]) return this.listeners[name](Object.assign({ target: this }, extra));
  }
  removeAttribute(name) { if (name === "src") this.src = ""; }
}
class FakeVideo extends FakeNode {
  constructor() {
    super("video");
    this.readyState = 0; this.paused = true; this.ended = false;
    this.currentTime = 0; this.duration = Number.NaN;
    this.volume = 1; this.playbackRate = 1; this.error = null;
  }
  pause() { this.paused = true; }
  load() {}
}
class FakeYTPlayer {
  constructor(element, options) {
    this.element = element;
    this.options = options;
    this.time = 0; this.duration = 26;
    this.state = -1; this.actions = [];
    FakeYTPlayer.last = this;
  }
  getPlayerState() { return this.state; }
  getCurrentTime() { return this.time; }
  getDuration() { return this.duration; }
  playVideo() { this.actions.push("play"); }
  pauseVideo() { this.actions.push("pause"); }
  seekTo(s) { this.actions.push(["seek", s]); }
  destroy() { this.destroyed = true; }
  ready() { this.options.events.onReady({ target: this }); }
  change(state) { this.state = state; this.options.events.onStateChange({ data: state, target: this }); }
  error(code) { this.options.events.onError({ data: code, target: this }); }
}
async function main() {
  let seq = 0;
  const revoked = [];
  let networkRequests = 0;
  const nodes = {};
  const ids = [
    "real-media-video", "real-media-file", "real-media-status",
    "real-media-rate", "real-media-volume", "real-media-rewind", "real-media-forward",
    "real-youtube-status", "real-youtube-url", "real-youtube-open",
    "real-youtube-player", "real-youtube-play", "real-youtube-pause",
    "real-youtube-back", "real-youtube-forward",
  ];
  ids.forEach(id => { nodes["#" + id] = id === "real-media-video" ? new FakeVideo() : new FakeNode(); });
  const root = { querySelector: selector => nodes[selector] };
  const timers = new Map();
  const context = {
    document: {
      createElement: tag => new FakeNode(tag),
      head: { appendChild() { networkRequests++; } },
    },
    location: { protocol: "http:", hostname: "localhost", origin: "http://localhost:44200" },
    navigator: { onLine: true },
    YT: { Player: FakeYTPlayer },
    URL: Object.assign(URL, {
      createObjectURL: () => "blob:local-" + (++seq),
      revokeObjectURL: v => revoked.push(v),
    }),
    setInterval(fn) { const id = ++seq; timers.set(id, fn); return id; },
    clearInterval(id) { timers.delete(id); },
    setTimeout() { throw new Error("Not needed with injected YT"); },
    clearTimeout() {},
    console,
  };
  context.window = context;
  context.globalThis = context;
  vm.runInNewContext(fs.readFileSync("web/youtube_iframe_playback_adapter.js", "utf8"), context);
  vm.runInNewContext(fs.readFileSync("web/real_media_workbench.js", "utf8"), context);
  const snapshots = [];
  const workbench = context.AccessibleChessRealMediaWorkbench.mount(root, s => snapshots.push(s));
  assert.throws(() => context.AccessibleChessRealMediaWorkbench.mount(root), /already mounted/);
  assert.equal(workbench.openLocal({name:"not-chess.exe",size:100,type:"application/octet-stream"}),false);
  assert.equal(snapshots.length, 0, "invalid local file must not publish a source");
  assert.equal(workbench.openLocal({name:"test.webm",size:8000,type:"video/webm"}),true);
  assert.equal(snapshots.at(-1).sourceKind,"local_file");
  assert.equal(snapshots.at(-1).sourceId,"local-file:session-1");
  assert.equal(snapshots.at(-1).chessRef,null);
  assert.equal(snapshots.at(-1).qualification,"unlinked");
  assert(Object.isFrozen(snapshots.at(-1)));
  assert.equal(networkRequests,0,"local playback must not depend on provider network");
  const video = nodes["#real-media-video"];
  video.duration = 26; video.readyState = 4; video.currentTime = 7; video.paused = false;
  video.emit("loadedmetadata");
  assert.equal(snapshots.at(-1).positionMs,7000);
  assert.equal(snapshots.at(-1).durationMs,26000);
  assert.equal(snapshots.at(-1).playbackState,"playing");
  nodes["#real-media-rewind"].emit("click"); assert.equal(video.currentTime,0);
  nodes["#real-media-forward"].emit("click"); assert.equal(video.currentTime,10);
  nodes["#real-media-rate"].value = "1.5"; nodes["#real-media-rate"].emit("change");
  assert.equal(video.playbackRate,1.5);
  nodes["#real-media-volume"].value = "35"; nodes["#real-media-volume"].emit("change");
  assert.equal(video.volume,0.35);
  video.error = { code: 4 }; video.emit("error");
  assert.equal(snapshots.at(-1).ok,false);
  assert(nodes["#real-media-status"].textContent.includes("Кодек"));
  video.error = null;
  assert.equal(workbench.openLocal({name:"another.mp4",size:1,type:"video/mp4"}),true);
  assert.deepEqual(revoked,["blob:local-1"],"old video URL must be revoked on reopen");
  assert.equal(workbench.localSnapshot().sourceId,"local-file:session-2");
  assert.equal(networkRequests,0);
  assert.equal(workbench.openLocal({name:"x.webm",size:1,type:"text/html"}),false);
  assert.equal(workbench.localSnapshot().sourceId,"local-file:session-2");

  nodes["#real-youtube-url"].value = "https://youtu.be/dQw4w9WgXcQ";
  assert.equal(await workbench.openYouTube(),true);
  const yt = FakeYTPlayer.last;
  assert.equal(yt.options.videoId,"dQw4w9WgXcQ");
  assert.equal(yt.options.playerVars.autoplay,0);
  yt.ready();
  assert.equal(snapshots.at(-1).sourceKind,"remote_media");
  yt.time = 5.25; yt.change(1);
  assert.equal(snapshots.at(-1).positionMs,5250);
  assert.equal(snapshots.at(-1).qualification,"unlinked");
  nodes["#real-youtube-play"].emit("click");
  nodes["#real-youtube-pause"].emit("click");
  nodes["#real-youtube-forward"].emit("click");
  assert.equal(yt.actions[0],"play"); assert.equal(yt.actions[1],"pause");
  assert.deepEqual(yt.actions[2],["seek",15.25]);
  yt.error(101);
  assert.equal(snapshots.at(-1).ok,false);
  assert(nodes["#real-youtube-status"].textContent.includes("101"));
  assert.equal(networkRequests,0,"injected YT API should not download raw content");
  nodes["#real-youtube-url"].value = "https://youtube.evil.example/watch?v=dQw4w9WgXcQ";
  assert.equal(await workbench.openYouTube(),false);
  assert(nodes["#real-youtube-status"].textContent.includes("Невірне"));
  context.navigator.onLine = false;
  nodes["#real-youtube-url"].value = "dQw4w9WgXcQ";
  assert.equal(await workbench.openYouTube(),false);
  assert(nodes["#real-youtube-status"].textContent.includes("офлайн"));
  assert(workbench.localSnapshot(),"YouTube loss must not destroy local MP4");
  assert.equal(workbench.close(),true);
  assert.equal(workbench.close(),false);
  assert.deepEqual(revoked,["blob:local-1","blob:local-3"]);
  assert.equal(timers.size,0);
  assert.equal(workbench.localSnapshot(),null);
  console.log("section47_48_real_media_workbench_test: PASS; local reopen/error/seek/rate/volume, remote API events/errors/offline and isolation");
}
main().catch(e => { console.error(e); process.exitCode = 1; });
