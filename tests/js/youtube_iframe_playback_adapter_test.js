"use strict";

const fs = require("fs");
const vm = require("vm");

global.window = {};
vm.runInThisContext(
  fs.readFileSync("web/youtube_iframe_playback_adapter.js", "utf8"),
  { filename: "youtube_iframe_playback_adapter.js" },
);

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function expectThrow(fn, fragment) {
  let thrown = false;
  try {
    fn();
  } catch (error) {
    thrown = String(error).includes(fragment);
  }
  check(thrown, `expected error containing: ${fragment}`);
}

class FakePlayer {
  constructor(element, options) {
    this.element = element;
    this.options = options;
    this.state = -1;
    this.time = 0;
    this.duration = 120;
    this.calls = [];
    this.destroyed = false;
    FakePlayer.instances.push(this);
  }

  getPlayerState() { return this.state; }
  getCurrentTime() { return this.time; }
  getDuration() { return this.duration; }
  playVideo() { this.calls.push(["playVideo"]); }
  pauseVideo() { this.calls.push(["pauseVideo"]); }
  seekTo(seconds, allowSeekAhead) { this.calls.push(["seekTo", seconds, allowSeekAhead]); }
  destroy() { this.destroyed = true; this.calls.push(["destroy"]); }
  ready() { this.options.events.onReady({ target: this }); }
  change(state) { this.state = state; this.options.events.onStateChange({ data: state, target: this }); }
  error(code) { this.options.events.onError({ data: code, target: this }); }
}
FakePlayer.instances = [];

const api = window.AccessibleChessYouTubeIframePlayback;
check(api && typeof api.parseVideoId === "function", "YouTube adapter API is missing");

for (const source of [
  "dQw4w9WgXcQ",
  "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "https://youtu.be/dQw4w9WgXcQ?t=15",
  "https://www.youtube.com/shorts/dQw4w9WgXcQ",
  "https://youtube.com/live/dQw4w9WgXcQ?feature=share",
  "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
]) {
  check(api.parseVideoId(source) === "dQw4w9WgXcQ", `source did not canonicalize: ${source}`);
}

for (const [source, fragment] of [
  ["http://youtube.com/watch?v=dQw4w9WgXcQ", "HTTPS"],
  ["https://youtube.com/watch?v=dQw4w9WgXcQ&v=aaaaaaaaaaa", "one video id"],
  ["https://youtube.com/watch?v=dQw4w9WgXcQ&list=PL123", "playlists"],
  ["https://youtube.example/watch?v=dQw4w9WgXcQ", "unsupported"],
  ["https://user:secret@youtube.com/watch?v=dQw4w9WgXcQ", "authority"],
  ["https://youtube.com:444/watch?v=dQw4w9WgXcQ", "authority"],
  ["https://youtu.be/not-valid", "video id"],
]) {
  expectThrow(() => api.parseVideoId(source), fragment);
}

const snapshots = [];
const YT = { Player: FakePlayer };
const adapter = new api.YouTubeIframePlaybackAdapter({
  YT,
  element: "youtube-player",
  source: "https://youtu.be/dQw4w9WgXcQ?t=5",
  origin: "https://appassets.example",
  onSnapshot: (snapshot) => snapshots.push(snapshot),
});
const player = FakePlayer.instances.at(-1);
check(player.options.videoId === "dQw4w9WgXcQ", "canonical video id was not passed to IFrame API");
check(player.options.playerVars.enablejsapi === 1, "enablejsapi was not enabled");
check(player.options.playerVars.autoplay === 0, "provider adapter enabled autoplay");
check(player.options.playerVars.origin === "https://appassets.example", "canonical origin was not passed");
check(!("caption" in player.options.playerVars), "adapter invented caption extraction controls");
expectThrow(() => adapter.play(), "not ready");

player.time = 12.345;
player.duration = 125.5;
player.ready();
check(snapshots.length === 1, "ready snapshot was not published exactly once");
check(snapshots[0].sourceId === "youtube:dQw4w9WgXcQ", "snapshot leaked noncanonical source URL");
check(snapshots[0].sourceKind === "remote_media", "remote media source kind is wrong");
check(snapshots[0].positionMs === 12345, "current time was not converted to milliseconds");
check(snapshots[0].durationMs === 125500, "duration was not converted to milliseconds");
check(snapshots[0].playbackState === "unstarted", "ready state mapping is wrong");
check(Object.isFrozen(snapshots[0]), "published snapshot is mutable");

player.change(1);
check(snapshots.at(-1).playbackState === "playing", "playing state mapping failed");
player.change(2);
check(snapshots.at(-1).playbackState === "paused", "paused state mapping failed");
player.change(3);
check(snapshots.at(-1).playbackState === "buffering", "buffering state mapping failed");
player.change(0);
check(snapshots.at(-1).playbackState === "ended", "ended state mapping failed");
player.change(5);
check(snapshots.at(-1).playbackState === "unstarted", "cued state mapping failed");
expectThrow(() => player.change(4), "unsupported YouTube player state");
player.state = 2;

adapter.play();
adapter.pause();
adapter.seek(60000);
check(JSON.stringify(player.calls.slice(-3)) === JSON.stringify([
  ["playVideo"],
  ["pauseVideo"],
  ["seekTo", 60, true],
]), "playback commands did not delegate exactly to IFrame API");
expectThrow(() => adapter.seek(-1), "non-negative integer");
expectThrow(() => adapter.seek(126000), "exceeds YouTube duration");

const beforeRefresh = snapshots.length;
const refreshed = adapter.refresh();
check(snapshots.length === beforeRefresh + 1, "refresh did not publish one snapshot");
check(refreshed.sourceId === "youtube:dQw4w9WgXcQ", "refresh changed source identity");

player.error(101);
check(snapshots.at(-1).ok === false && snapshots.at(-1).errorCode === 101, "provider error did not fail closed");
expectThrow(() => adapter.pause(), "provider error");

check(adapter.destroy() === true, "first destroy did not report completion");
check(player.destroyed === true, "IFrame player was not destroyed");
check(adapter.destroy() === false, "second destroy was not idempotent");
expectThrow(() => adapter.snapshot(), "destroyed");

expectThrow(
  () => new api.YouTubeIframePlaybackAdapter({
    YT,
    element: "x",
    source: "dQw4w9WgXcQ",
    origin: "http://example.com",
  }),
  "HTTPS or loopback HTTP",
);
new api.YouTubeIframePlaybackAdapter({
  YT,
  element: "loopback",
  source: "dQw4w9WgXcQ",
  origin: "http://localhost:8765",
}).destroy();

const badTime = new api.YouTubeIframePlaybackAdapter({
  YT,
  element: "bad-time",
  source: "dQw4w9WgXcQ",
  origin: "https://appassets.example",
});
const badPlayer = FakePlayer.instances.at(-1);
badPlayer.ready();
badPlayer.time = Number.NaN;
expectThrow(() => badTime.snapshot(), "current time");
badTime.destroy();

check(typeof api.YouTubeIframePlaybackAdapter.prototype.download !== "function", "adapter exposes a download surface");
check(typeof api.YouTubeIframePlaybackAdapter.prototype.captions !== "function", "adapter exposes an undocumented caption surface");
console.log("youtube_iframe_playback_adapter_test: ok");
